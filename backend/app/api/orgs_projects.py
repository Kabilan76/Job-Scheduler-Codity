from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.app.db import get_db
from backend.app.models import Organization, OrgMember, Project, User
from backend.app.schemas import OrganizationCreate, OrganizationOut, ProjectCreate, ProjectOut
from backend.app.api.auth import get_current_user

router = APIRouter(tags=["organizations & projects"])

@router.get("/organizations", response_model=List[OrganizationOut])
async def get_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Retrieve organizations owned by user or where user is a member
    query = (
        select(Organization)
        .outerjoin(OrgMember, Organization.id == OrgMember.org_id)
        .where((Organization.owner_id == current_user.id) | (OrgMember.user_id == current_user.id))
        .distinct()
    )
    result = await db.execute(query)
    orgs = result.scalars().all()
    return orgs

@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_in: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_org = Organization(
        name=org_in.name,
        owner_id=current_user.id
    )
    db.add(new_org)
    await db.flush()
    
    # Add creator as owner in members list
    member = OrgMember(
        org_id=new_org.id,
        user_id=current_user.id,
        role="owner"
    )
    db.add(member)
    await db.commit()
    await db.refresh(new_org)
    return new_org

@router.get("/projects", response_model=List[ProjectOut])
async def get_projects(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify membership in org
    membership_query = select(OrgMember).where(
        (OrgMember.org_id == org_id) & (OrgMember.user_id == current_user.id)
    )
    membership_res = await db.execute(membership_query)
    org_res = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_res.scalars().first()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
        
    if org.owner_id != current_user.id and not membership_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Not authorized to access this organization"
        )
        
    result = await db.execute(select(Project).where(Project.org_id == org_id))
    projects = result.scalars().all()
    return projects

@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify user has access to create projects in this org
    org_res = await db.execute(select(Organization).where(Organization.id == project_in.org_id))
    org = org_res.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
        
    if org.owner_id != current_user.id:
        membership_query = select(OrgMember).where(
            (OrgMember.org_id == project_in.org_id) & 
            (OrgMember.user_id == current_user.id) & 
            (OrgMember.role.in_(["owner", "admin"]))
        )
        mem_res = await db.execute(membership_query)
        if not mem_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to create projects in this organization"
            )
            
    new_project = Project(
        org_id=project_in.org_id,
        name=project_in.name
    )
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return new_project
