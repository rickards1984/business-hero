"""
Accounting module for Business Hero.
Handles spreadsheet uploads, transaction management, and financial analysis.
"""

import csv
import io
import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlmodel import Session, select, func, or_, and_
from pydantic import BaseModel

from models import Business
from db import get_session
from dependencies import get_current_user_and_business

import os

_logger = logging.getLogger("accounting")

router = APIRouter(prefix="/v1/accounting", tags=["accounting"])


# ============== Pydantic Models ==============

class CategoryCreate(BaseModel):
    name: str
    type: str  # 'income' or 'expense'
    color: Optional[str] = '#6B7280'

class TransactionCreate(BaseModel):
    transaction_date: date
    description: str
    amount: float
    type: str  # 'income' or 'expense'
    category_id: Optional[str] = None
    reference: Optional[str] = None
    payee_payer: Optional[str] = None
    account: Optional[str] = None
    notes: Optional[str] = None

class TransactionUpdate(BaseModel):
    transaction_date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    type: Optional[str] = None
    category_id: Optional[str] = None
    reference: Optional[str] = None
    payee_payer: Optional[str] = None
    notes: Optional[str] = None
    is_reconciled: Optional[bool] = None

class ColumnMapping(BaseModel):
    date_column: str
    description_column: str
    amount_column: str
    type_column: Optional[str] = None  # If separate income/expense columns
    income_column: Optional[str] = None
    expense_column: Optional[str] = None
    reference_column: Optional[str] = None
    payee_column: Optional[str] = None


class BulkDeleteTransactionsRequest(BaseModel):
    transaction_ids: List[str]


class UpdateTransactionRequest(BaseModel):
    category_id: Optional[str] = None
    description: Optional[str] = None
    payee_payer: Optional[str] = None


class BulkUpdateCategoryRequest(BaseModel):
    transaction_ids: List[str]
    category_id: Optional[str] = None


# ============== Categories Endpoints ==============

@router.get("/categories")
async def list_categories(
    type: Optional[str] = Query(None, description="Filter by 'income' or 'expense'"),
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """List all accounting categories for the business."""
    _, business = user_business
    
    from sqlalchemy import text
    
    query = """
        SELECT id, name, type, color, icon, is_default, created_at
        FROM accounting_categories
        WHERE business_id = :business_id
    """
    params = {"business_id": str(business.id)}
    
    if type:
        query += " AND type = :type"
        params["type"] = type
    
    query += " ORDER BY is_default DESC, name ASC"
    
    with session.connection() as conn:
        result = conn.execute(text(query), params)
        categories = [
            {
                "id": str(row[0]),
                "name": row[1],
                "type": row[2],
                "color": row[3],
                "icon": row[4],
                "is_default": row[5],
                "created_at": row[6].isoformat() if row[6] else None
            }
            for row in result.fetchall()
        ]
    
    return {"categories": categories, "count": len(categories)}


@router.post("/categories")
async def create_category(
    category: CategoryCreate,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Create a new accounting category."""
    _, business = user_business
    
    if category.type not in ('income', 'expense'):
        raise HTTPException(status_code=400, detail="Type must be 'income' or 'expense'")
    
    from sqlalchemy import text
    
    try:
        result = session.execute(
            text("""
                INSERT INTO accounting_categories (business_id, name, type, color)
                VALUES (:business_id, :name, :type, :color)
                RETURNING id, name, type, color, created_at
            """),
            {
                "business_id": str(business.id),
                "name": category.name,
                "type": category.type,
                "color": category.color or '#6B7280'
            }
        )
        row = result.fetchone()
        session.commit()
        
        return {
            "id": str(row[0]),
            "name": row[1],
            "type": row[2],
            "color": row[3],
            "created_at": row[4].isoformat() if row[4] else None
        }
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Category with this name already exists")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Transactions Endpoints ==============

@router.get("/transactions")
async def list_transactions(
    type: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    is_reconciled: Optional[bool] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """List transactions with filtering and pagination."""
    _, business = user_business
    
    from sqlalchemy import text
    
    query = """
        SELECT 
            t.id, t.transaction_date, t.description, t.amount, t.type,
            t.reference, t.payee_payer, t.account, t.notes,
            t.is_reconciled, t.created_at,
            c.id as category_id, c.name as category_name, c.color as category_color
        FROM accounting_transactions t
        LEFT JOIN accounting_categories c ON t.category_id = c.id
        WHERE t.business_id = :business_id AND t.is_archived = false
    """
    params = {"business_id": str(business.id)}
    
    if type:
        query += " AND t.type = :type"
        params["type"] = type
    
    if category_id:
        query += " AND t.category_id = :category_id"
        params["category_id"] = category_id
    
    if start_date:
        query += " AND t.transaction_date >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND t.transaction_date <= :end_date"
        params["end_date"] = end_date
    
    if search:
        query += " AND (t.description ILIKE :search OR t.payee_payer ILIKE :search OR t.reference ILIKE :search)"
        params["search"] = f"%{search}%"
    
    if is_reconciled is not None:
        query += " AND t.is_reconciled = :is_reconciled"
        params["is_reconciled"] = is_reconciled
    
    # Count total
    count_query = f"SELECT COUNT(*) FROM ({query}) subq"
    
    # Add ordering and pagination
    query += " ORDER BY t.transaction_date DESC, t.created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    
    with session.connection() as conn:
        # Get total count
        total = conn.execute(text(count_query), {k: v for k, v in params.items() if k not in ('limit', 'offset')}).scalar()
        
        # Get transactions
        result = conn.execute(text(query), params)
        transactions = [
            {
                "id": str(row[0]),
                "transaction_date": row[1].isoformat() if row[1] else None,
                "description": row[2],
                "amount": float(row[3]) if row[3] else 0,
                "type": row[4],
                "reference": row[5],
                "payee_payer": row[6],
                "account": row[7],
                "notes": row[8],
                "is_reconciled": row[9],
                "created_at": row[10].isoformat() if row[10] else None,
                "category": {
                    "id": str(row[11]),
                    "name": row[12],
                    "color": row[13]
                } if row[11] else None
            }
            for row in result.fetchall()
        ]
    
    return {
        "transactions": transactions,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.post("/transactions")
async def create_transaction(
    transaction: TransactionCreate,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Create a single transaction."""
    _, business = user_business
    
    from sqlalchemy import text
    
    result = session.execute(
        text("""
            INSERT INTO accounting_transactions 
            (business_id, transaction_date, description, amount, type, category_id, reference, payee_payer, account, notes)
            VALUES (:business_id, :transaction_date, :description, :amount, :type, :category_id, :reference, :payee_payer, :account, :notes)
            RETURNING id
        """),
        {
            "business_id": str(business.id),
            "transaction_date": transaction.transaction_date,
            "description": transaction.description,
            "amount": abs(transaction.amount) if transaction.type == 'income' else -abs(transaction.amount),
            "type": transaction.type,
            "category_id": transaction.category_id,
            "reference": transaction.reference,
            "payee_payer": transaction.payee_payer,
            "account": transaction.account,
            "notes": transaction.notes
        }
    )
    transaction_id = result.fetchone()[0]
    session.commit()
    
    return {"id": str(transaction_id), "success": True}


@router.patch("/transactions/{transaction_id}")
async def update_transaction(
    transaction_id: str,
    updates: TransactionUpdate,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Update a transaction."""
    _, business = user_business
    
    from sqlalchemy import text
    
    # Build dynamic update query
    update_fields = []
    params = {"transaction_id": transaction_id, "business_id": str(business.id)}
    
    for field, value in updates.dict(exclude_unset=True).items():
        if value is not None:
            update_fields.append(f"{field} = :{field}")
            params[field] = value
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_fields.append("updated_at = NOW()")
    
    query = f"""
        UPDATE accounting_transactions 
        SET {', '.join(update_fields)}
        WHERE id = :transaction_id AND business_id = :business_id
        RETURNING id
    """
    
    result = session.execute(text(query), params)
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    session.commit()
    return {"success": True}


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Delete (archive) a transaction."""
    _, business = user_business
    
    from sqlalchemy import text
    
    result = session.execute(
        text("""
            UPDATE accounting_transactions 
            SET is_archived = true, updated_at = NOW()
            WHERE id = :transaction_id AND business_id = :business_id
            RETURNING id
        """),
        {"transaction_id": transaction_id, "business_id": str(business.id)}
    )
    
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    session.commit()
    return {"success": True}


@router.post("/transactions/bulk-delete")
async def bulk_delete_transactions(
    request: BulkDeleteTransactionsRequest,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Soft delete multiple transactions at once."""
    _, business = user_business
    business_id = str(business.id)
    
    from sqlalchemy import text
    
    result = session.execute(
        text("""
            UPDATE accounting_transactions 
            SET is_archived = true, updated_at = NOW()
            WHERE business_id = :business_id 
            AND id = ANY(CAST(:transaction_ids AS uuid[]))
            AND is_archived = false
            RETURNING id
        """),
        {
            "business_id": str(business.id),
            "transaction_ids": request.transaction_ids
        }
    )
    deleted_ids = [str(row[0]) for row in result.fetchall()]
    session.commit()
    
    return {"deleted_count": len(deleted_ids), "deleted_ids": deleted_ids}


@router.post("/transactions/bulk-update-category")
async def bulk_update_category(
    request: BulkUpdateCategoryRequest,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Assign a category to multiple transactions at once."""
    _, business = user_business
    
    from sqlalchemy import text
    
    result = session.execute(
        text("""
            UPDATE accounting_transactions 
            SET category_id = :category_id, updated_at = NOW()
            WHERE business_id = :business_id 
            AND id = ANY(CAST(:transaction_ids AS uuid[]))
            AND is_archived = false
            RETURNING id
        """),
        {
            "business_id": str(business.id),
            "category_id": request.category_id if request.category_id else None,
            "transaction_ids": request.transaction_ids
        }
    )
    updated_ids = [str(row[0]) for row in result.fetchall()]
    session.commit()
    
    return {"updated_count": len(updated_ids), "updated_ids": updated_ids}


# ============== Upload & Import Endpoints ==============

@router.post("/upload/analyze")
async def analyze_spreadsheet(
    file: UploadFile = File(...),
    user_business=Depends(get_current_user_and_business),
):
    """
    Analyze an uploaded spreadsheet and detect column mappings using AI.
    Returns suggested mappings for user confirmation.
    """
    _, business = user_business
    
    # Read file content
    content = await file.read()
    
    # Determine file type and parse
    filename = file.filename.lower()
    
    try:
        if filename.endswith('.csv'):
            rows = _parse_csv(content)
        elif filename.endswith(('.xlsx', '.xls')):
            rows = _parse_excel(content)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Please upload CSV or Excel file.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")
    
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="File must contain headers and at least one data row")
    
    headers = rows[0]
    sample_rows = rows[1:6]  # First 5 data rows for analysis
    
    # Use AI to detect column mappings
    mapping_suggestion = await _detect_column_mapping(headers, sample_rows)
    _logger.info(f"Suggested mapping for columns {headers}: {mapping_suggestion}")
    
    return {
        "filename": file.filename,
        "headers": headers,
        "sample_rows": sample_rows,
        "row_count": len(rows) - 1,
        "suggested_mapping": mapping_suggestion
    }


@router.post("/upload/import")
async def import_spreadsheet(
    file: UploadFile = File(...),
    mapping: str = Form(...),  # JSON string of ColumnMapping
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """
    Import transactions from spreadsheet using confirmed column mapping.
    """
    _, business = user_business
    
    # Parse mapping
    try:
        mapping_dict = json.loads(mapping)
    except:
        raise HTTPException(status_code=400, detail="Invalid mapping JSON")
    
    # Read and parse file
    content = await file.read()
    filename = file.filename.lower()
    
    try:
        if filename.endswith('.csv'):
            rows = _parse_csv(content)
        elif filename.endswith(('.xlsx', '.xls')):
            rows = _parse_excel(content)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")
    
    headers = rows[0]
    data_rows = rows[1:]
    
    from sqlalchemy import text
    
    # Create import record
    import_result = session.execute(
        text("""
            INSERT INTO accounting_imports (business_id, filename, original_filename, row_count, status, column_mapping)
            VALUES (:business_id, :filename, :original_filename, :row_count, 'processing', :column_mapping)
            RETURNING id
        """),
        {
            "business_id": str(business.id),
            "filename": file.filename,
            "original_filename": file.filename,
            "row_count": len(data_rows),
            "column_mapping": json.dumps(mapping_dict)
        }
    )
    import_id = str(import_result.fetchone()[0])
    session.commit()
    
    # Process rows
    success_count = 0
    error_count = 0
    errors = []
    
    # Get column indices
    header_map = {h.lower().strip(): i for i, h in enumerate(headers)}
    
    # Debug logging
    _logger.info(f"Import mapping received: {mapping_dict}")
    _logger.info(f"Headers from file: {headers}")
    _logger.info(f"Header map (lowercase): {header_map}")
    
    date_col = _find_column_index(header_map, mapping_dict.get('date_column'))
    desc_col = _find_column_index(header_map, mapping_dict.get('description_column'))
    amount_col = _find_column_index(header_map, mapping_dict.get('amount_column'))
    type_col = _find_column_index(header_map, mapping_dict.get('type_column'))
    income_col = _find_column_index(header_map, mapping_dict.get('income_column'))
    expense_col = _find_column_index(header_map, mapping_dict.get('expense_column'))
    ref_col = _find_column_index(header_map, mapping_dict.get('reference_column'))
    payee_col = _find_column_index(header_map, mapping_dict.get('payee_column'))
    category_col = _find_column_index(header_map, mapping_dict.get('category_column'))
    
    _logger.info(f"Column indices - date: {date_col}, desc: {desc_col}, amount: {amount_col}, income: {income_col}, expense: {expense_col}, category: {category_col}")
    
    # Build a lookup dict of existing categories (name -> id)
    category_lookup = {}
    if category_col is not None:
        existing_categories = session.execute(
            text("SELECT id, name FROM accounting_categories WHERE business_id = :business_id"),
            {"business_id": str(business.id)}
        ).fetchall()
        category_lookup = {cat[1].lower().strip(): str(cat[0]) for cat in existing_categories}
    
    for row_num, row in enumerate(data_rows, start=2):
        try:
            # Parse date
            date_val = _parse_date(row[date_col]) if date_col is not None else None
            if not date_val:
                errors.append(f"Row {row_num}: Invalid date")
                error_count += 1
                continue
            
            # Parse description
            description = str(row[desc_col]).strip() if desc_col is not None and desc_col < len(row) else ""
            if not description:
                description = "Imported transaction"
            
            # Parse amount and type
            amount = 0.0
            trans_type = 'expense'
            
            if income_col is not None or expense_col is not None:
                # Separate income/expense columns (one or both may be mapped)
                income_val = 0
                expense_val = 0
                
                if income_col is not None and income_col < len(row):
                    income_val = _parse_amount(row[income_col]) or 0
                if expense_col is not None and expense_col < len(row):
                    expense_val = _parse_amount(row[expense_col]) or 0
                
                if income_val > 0:
                    amount = income_val
                    trans_type = 'income'
                elif expense_val > 0:
                    amount = expense_val  # Store as positive, type indicates it's expense
                    trans_type = 'expense'
                else:
                    # Both are zero/empty - skip this row silently (likely a header or empty row)
                    continue
            elif amount_col is not None:
                # Single amount column
                amount = _parse_amount(row[amount_col]) if amount_col < len(row) else 0
                
                if amount == 0:
                    continue
                
                # Determine type
                if type_col is not None and type_col < len(row):
                    type_str = str(row[type_col]).lower().strip()
                    if type_str in ('income', 'credit', 'in', 'cr', 'deposit'):
                        trans_type = 'income'
                        amount = abs(amount)
                    else:
                        trans_type = 'expense'
                        amount = -abs(amount)
                else:
                    # Guess based on sign
                    if amount > 0:
                        trans_type = 'income'
                    else:
                        trans_type = 'expense'
            else:
                errors.append(f"Row {row_num}: No amount column configured")
                error_count += 1
                continue
            
            # Optional fields
            reference = str(row[ref_col]).strip() if ref_col is not None and ref_col < len(row) else None
            payee = str(row[payee_col]).strip() if payee_col is not None and payee_col < len(row) else None
            
            # Handle category from CSV
            category_id = None
            if category_col is not None and category_col < len(row):
                category_name = str(row[category_col]).strip() if row[category_col] else None
                if category_name:
                    # Look up existing category (case-insensitive)
                    category_id = category_lookup.get(category_name.lower())
                    
                    # If category doesn't exist, create it
                    if not category_id:
                        try:
                            # First check if it exists (in case lookup missed it)
                            existing = session.execute(
                                text("""
                                    SELECT id FROM accounting_categories 
                                    WHERE business_id = :business_id AND LOWER(name) = LOWER(:name)
                                """),
                                {"business_id": str(business.id), "name": category_name}
                            ).fetchone()
                            
                            if existing:
                                category_id = str(existing[0])
                            else:
                                # Create new category
                                new_cat_result = session.execute(
                                    text("""
                                        INSERT INTO accounting_categories (business_id, name, type, color, created_at, updated_at)
                                        VALUES (:business_id, :name, :cat_type, '#6B7280', NOW(), NOW())
                                        RETURNING id
                                    """),
                                    {"business_id": str(business.id), "name": category_name, "cat_type": trans_type}
                                )
                                new_cat_row = new_cat_result.fetchone()
                                if new_cat_row:
                                    category_id = str(new_cat_row[0])
                            
                            # Add to lookup for future rows
                            if category_id:
                                category_lookup[category_name.lower()] = category_id
                                
                        except Exception as e:
                            # Log but don't fail the entire import for category issues
                            _logger.warning(f"Could not create category '{category_name}': {e}")
                            category_id = None
            
            # Insert transaction
            session.execute(
                text("""
                    INSERT INTO accounting_transactions 
                    (business_id, import_id, transaction_date, description, amount, type, reference, payee_payer, category_id)
                    VALUES (:business_id, :import_id, :transaction_date, :description, :amount, :type, :reference, :payee_payer, :category_id)
                """),
                {
                    "business_id": str(business.id),
                    "import_id": import_id,
                    "transaction_date": date_val,
                    "description": description,
                    "amount": amount,
                    "type": trans_type,
                    "reference": reference,
                    "payee_payer": payee,
                    "category_id": category_id
                }
            )
            success_count += 1
            
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
            error_count += 1
    
    # Update import record
    session.execute(
        text("""
            UPDATE accounting_imports 
            SET status = 'completed', success_count = :success_count, error_count = :error_count, completed_at = NOW()
            WHERE id = :import_id
        """),
        {"import_id": import_id, "success_count": success_count, "error_count": error_count}
    )
    session.commit()
    
    return {
        "import_id": import_id,
        "success_count": success_count,
        "error_count": error_count,
        "errors": errors[:10]  # Return first 10 errors
    }


# ============== Summary & Analytics Endpoints ==============

@router.get("/summary")
async def get_accounting_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    period: Optional[str] = Query("month", description="month, quarter, year, all"),
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Get financial summary with totals and breakdowns."""
    _, business = user_business
    
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    # Determine date range
    today = date.today()
    
    if not start_date or not end_date:
        if period == "month":
            start_date = today.replace(day=1)
            end_date = today
        elif period == "quarter":
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1
            start_date = today.replace(month=quarter_start_month, day=1)
            end_date = today
        elif period == "year":
            start_date = today.replace(month=1, day=1)
            end_date = today
        else:
            start_date = date(2000, 1, 1)
            end_date = today
    
    # Get totals
    totals_query = """
        SELECT 
            type,
            COUNT(*) as count,
            COALESCE(SUM(ABS(amount)), 0) as total
        FROM accounting_transactions
        WHERE business_id = :business_id 
          AND is_archived = false
          AND transaction_date >= :start_date 
          AND transaction_date <= :end_date
        GROUP BY type
    """
    
    with session.connection() as conn:
        result = conn.execute(
            text(totals_query), 
            {"business_id": str(business.id), "start_date": start_date, "end_date": end_date}
        )
        
        totals = {"income": 0, "expense": 0, "income_count": 0, "expense_count": 0}
        for row in result.fetchall():
            if row[0] == 'income':
                totals["income"] = float(row[2])
                totals["income_count"] = row[1]
            else:
                totals["expense"] = float(row[2])
                totals["expense_count"] = row[1]
        
        totals["net"] = totals["income"] - totals["expense"]
        totals["transaction_count"] = totals["income_count"] + totals["expense_count"]
        
        # Get category breakdown
        category_query = """
            SELECT 
                c.name, c.color, t.type,
                COUNT(*) as count,
                COALESCE(SUM(ABS(t.amount)), 0) as total
            FROM accounting_transactions t
            LEFT JOIN accounting_categories c ON t.category_id = c.id
            WHERE t.business_id = :business_id 
              AND t.is_archived = false
              AND t.transaction_date >= :start_date 
              AND t.transaction_date <= :end_date
            GROUP BY c.name, c.color, t.type
            ORDER BY total DESC
        """
        
        result = conn.execute(
            text(category_query),
            {"business_id": str(business.id), "start_date": start_date, "end_date": end_date}
        )
        
        categories_income = []
        categories_expense = []
        
        for row in result.fetchall():
            cat_data = {
                "name": row[0] or "Uncategorized",
                "color": row[1] or "#6B7280",
                "count": row[3],
                "total": float(row[4])
            }
            if row[2] == 'income':
                categories_income.append(cat_data)
            else:
                categories_expense.append(cat_data)
        
        # Get monthly trend (last 6 months)
        trend_query = """
            SELECT 
                DATE_TRUNC('month', transaction_date) as month,
                type,
                COALESCE(SUM(ABS(amount)), 0) as total
            FROM accounting_transactions
            WHERE business_id = :business_id 
              AND is_archived = false
              AND transaction_date >= :trend_start
            GROUP BY DATE_TRUNC('month', transaction_date), type
            ORDER BY month
        """
        
        trend_start = today - timedelta(days=180)  # Approximately 6 months
        result = conn.execute(
            text(trend_query),
            {"business_id": str(business.id), "trend_start": trend_start}
        )
        
        trend_data = {}
        for row in result.fetchall():
            month_key = row[0].strftime("%Y-%m")
            if month_key not in trend_data:
                trend_data[month_key] = {"month": month_key, "income": 0, "expense": 0}
            if row[1] == 'income':
                trend_data[month_key]["income"] = float(row[2])
            else:
                trend_data[month_key]["expense"] = float(row[2])
        
        trend = list(trend_data.values())
    
    return {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "label": period
        },
        "totals": totals,
        "categories": {
            "income": categories_income,
            "expense": categories_expense
        },
        "trend": trend
    }


@router.get("/imports")
async def list_imports(
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """List import history."""
    _, business = user_business
    
    from sqlalchemy import text
    
    result = session.execute(
        text("""
            SELECT id, filename, row_count, success_count, error_count, status, created_at, completed_at
            FROM accounting_imports
            WHERE business_id = :business_id
            ORDER BY created_at DESC
            LIMIT 20
        """),
        {"business_id": str(business.id)}
    )
    
    imports = [
        {
            "id": str(row[0]),
            "filename": row[1],
            "row_count": row[2],
            "success_count": row[3],
            "error_count": row[4],
            "status": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "completed_at": row[7].isoformat() if row[7] else None
        }
        for row in result.fetchall()
    ]
    
    return {"imports": imports}


# ============== Helper Functions ==============

def _parse_csv(content: bytes) -> List[List[str]]:
    """Parse CSV content into rows."""
    text_content = content.decode('utf-8-sig')  # Handle BOM
    reader = csv.reader(io.StringIO(text_content))
    return list(reader)


def _parse_excel(content: bytes) -> List[List[str]]:
    """Parse Excel content into rows."""
    import openpyxl
    from io import BytesIO
    
    wb = openpyxl.load_workbook(BytesIO(content), read_only=True)
    ws = wb.active
    
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(cell) if cell is not None else "" for cell in row])
    
    return rows


def _find_column_index(header_map: dict, column_name: str) -> Optional[int]:
    """Find column index by name (case-insensitive)."""
    if not column_name:
        return None
    return header_map.get(column_name.lower().strip())


def _parse_date(value) -> Optional[date]:
    """Parse various date formats."""
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    
    value = str(value).strip()
    
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
        "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
        "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except:
            continue
    
    return None


def _parse_amount(value) -> float:
    """Parse amount from various formats."""
    if isinstance(value, (int, float)):
        return float(value)
    
    value = str(value).strip()
    
    # Remove currency symbols and thousands separators
    value = value.replace('£', '').replace('$', '').replace('€', '')
    value = value.replace(',', '').replace(' ', '')
    
    # Handle parentheses as negative
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    
    try:
        return float(value)
    except:
        return 0.0


async def _detect_column_mapping(headers: List[str], sample_rows: List[List[str]]) -> dict:
    """Use AI to detect column mappings from headers and sample data."""
    
    # Simple heuristic detection first
    mapping = {}
    
    header_lower = [h.lower().strip() for h in headers]
    
    # Date column
    date_keywords = ['date', 'transaction date', 'trans date', 'posting date', 'value date']
    for kw in date_keywords:
        if kw in header_lower:
            mapping['date_column'] = headers[header_lower.index(kw)]
            break
    
    # Description column
    desc_keywords = ['description', 'desc', 'narrative', 'details', 'memo', 'particulars', 'transaction']
    for kw in desc_keywords:
        for i, h in enumerate(header_lower):
            if kw in h:
                mapping['description_column'] = headers[i]
                break
        if 'description_column' in mapping:
            break
    
    # Amount column
    amount_keywords = ['amount', 'value', 'sum', 'total']
    for kw in amount_keywords:
        for i, h in enumerate(header_lower):
            if kw in h and 'balance' not in h:
                mapping['amount_column'] = headers[i]
                break
        if 'amount_column' in mapping:
            break
    
    # Check for separate credit/debit columns
    credit_keywords = ['credit', 'income', 'money in', 'deposit', 'cr', 'paid in', 'credits', 'receipts', 'inflow']
    debit_keywords = ['debit', 'expense', 'money out', 'withdrawal', 'dr', 'payment', 'paid out', 'debits', 'payments', 'outflow']
    
    for kw in credit_keywords:
        for i, h in enumerate(header_lower):
            if kw in h:
                mapping['income_column'] = headers[i]
                break
    
    for kw in debit_keywords:
        for i, h in enumerate(header_lower):
            if kw in h:
                mapping['expense_column'] = headers[i]
                break
    
    # Reference column
    ref_keywords = ['reference', 'ref', 'invoice', 'check', 'cheque', 'transaction id']
    for kw in ref_keywords:
        for i, h in enumerate(header_lower):
            if kw in h:
                mapping['reference_column'] = headers[i]
                break
        if 'reference_column' in mapping:
            break
    
    # Payee column
    payee_keywords = ['payee', 'payer', 'vendor', 'customer', 'name', 'from', 'to']
    for kw in payee_keywords:
        for i, h in enumerate(header_lower):
            if h == kw or h.endswith(' ' + kw):
                mapping['payee_column'] = headers[i]
                break
    
    # Category column
    category_keywords = ['category', 'category name', 'cat', 'expense type', 'transaction category', 'expense category', 'income category']
    for kw in category_keywords:
        for i, h in enumerate(header_lower):
            if kw in h:
                mapping['category_column'] = headers[i]
                break
        if 'category_column' in mapping:
            break
    
    return mapping
