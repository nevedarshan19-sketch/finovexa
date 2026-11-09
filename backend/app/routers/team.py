from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmployeeEntry, User
from ..schemas import EmployeeCreateIn, EmployeeOut, EmployeeStatusIn
from ..security import get_current_owner, hash_password, rate_limit
from ..services.audit import log_audit
from ..services.business_context import ensure_membership, require_business
from ..services.employee_entries import entry_to_dict, entry_totals

router = APIRouter(prefix="/team", tags=["Team and employee entries"])


@router.get("/employees")
def list_employees(
    owner: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    employees = (
        db.query(User)
        .filter(User.owner_id == owner.id, User.role == "employee")
        .order_by(User.created_at.asc(), User.id.asc())
        .all()
    )
    entry_counts = dict(
        db.query(EmployeeEntry.employee_id, func.count(EmployeeEntry.id))
        .filter(EmployeeEntry.owner_id == owner.id)
        .group_by(EmployeeEntry.employee_id)
        .all()
    )
    items = []
    for employee in employees:
        payload = EmployeeOut.model_validate(employee).model_dump(mode="json")
        payload["entry_count"] = int(entry_counts.get(employee.id, 0))
        items.append(payload)
    return {
        "items": items,
        "count": len(items),
        "login_path": "/employee/login",
        "note": (
            "Employees sign in at /employee/login and can only create invoices, sales and purchase "
            "entries for your business. They cannot call owner APIs or see this dashboard."
        ),
    }


@router.post(
    "/employees",
    status_code=201,
    dependencies=[Depends(rate_limit("team_employee_create", 10, 60))],
)
def create_employee(
    payload: EmployeeCreateIn,
    owner: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    employee = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="employee",
        owner_id=owner.id,
        is_demo=False,
    )
    db.add(employee)
    db.flush()
    business = require_business(db, owner)
    ensure_membership(db, business.id, employee.id, "employee")
    log_audit(
        db,
        user_id=owner.id,
        actor=owner.email,
        action="team.employee_created",
        entity_type="user",
        entity_id=employee.id,
        detail={"email": employee.email, "name": employee.full_name},
    )
    db.commit()
    db.refresh(employee)
    return {
        "employee": EmployeeOut.model_validate(employee).model_dump(mode="json"),
        "login_path": "/employee/login",
        "message": "Employee account created. Share the employee portal link and credentials separately.",
    }


@router.patch("/employees/{employee_id}")
def update_employee_status(
    employee_id: int,
    payload: EmployeeStatusIn,
    owner: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    employee = (
        db.query(User)
        .filter(
            User.id == employee_id,
            User.owner_id == owner.id,
            User.role == "employee",
        )
        .one_or_none()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee account not found.")
    employee.is_active = payload.is_active
    log_audit(
        db,
        user_id=owner.id,
        actor=owner.email,
        action="team.employee_status_changed",
        entity_type="user",
        entity_id=employee.id,
        detail={"email": employee.email, "is_active": payload.is_active},
    )
    db.commit()
    db.refresh(employee)
    return {
        "employee": EmployeeOut.model_validate(employee).model_dump(mode="json"),
        "message": "Employee access updated.",
    }


@router.get("/entries")
def list_owner_employee_entries(
    entry_type: str = Query(default="all", pattern=r"^(all|invoice|sale|purchase)$"),
    status_filter: str = Query(default="all", alias="status", pattern=r"^(all|submitted|void)$"),
    employee_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    owner: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    query = db.query(EmployeeEntry).filter(EmployeeEntry.owner_id == owner.id)
    if entry_type != "all":
        query = query.filter(EmployeeEntry.entry_type == entry_type)
    if status_filter != "all":
        query = query.filter(EmployeeEntry.status == status_filter)
    if employee_id is not None:
        query = query.filter(EmployeeEntry.employee_id == employee_id)
    entries = query.order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc()).limit(limit).all()
    all_entries = (
        db.query(EmployeeEntry)
        .filter(EmployeeEntry.owner_id == owner.id)
        .order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc())
        .all()
    )
    return {
        "items": [entry_to_dict(db, entry) for entry in entries],
        "count": len(entries),
        "summary": entry_totals(all_entries),
        "note": (
            "Entries appear here as soon as an employee submits them. Employee-recorded cash and "
            "PayPal receipts are labelled as unverified in the ledger."
        ),
    }
