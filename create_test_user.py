import asyncio
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.future import select
from backend.app.db import engine, async_session_maker
from backend.app.models import User, Organization, OrgMember, Project
from backend.app.security import get_password_hash

async def seed_user():
    email = "lalith@gmail.com"
    password = "lalith007"
    name = "lalith"
    
    print(f"Checking for existing user {email}...")
    async with async_session_maker() as session:
        # Check if user exists
        res = await session.execute(select(User).where(User.email == email))
        user = res.scalars().first()
        
        if user:
            print(f"User {email} already exists. Updating password...")
            user.hashed_password = get_password_hash(password)
            user.name = name
            await session.commit()
            print("Password updated successfully!")
            return
            
        print("Creating user and default organization...")
        hashed_pw = get_password_hash(password)
        new_user = User(
            email=email,
            hashed_password=hashed_pw,
            name=name
        )
        session.add(new_user)
        await session.flush()
        
        # Org
        new_org = Organization(
            name="Lalith's Org",
            owner_id=new_user.id
        )
        session.add(new_org)
        await session.flush()
        
        # Membership
        member = OrgMember(
            org_id=new_org.id,
            user_id=new_user.id,
            role="owner"
        )
        session.add(member)
        
        # Project
        new_project = Project(
            org_id=new_org.id,
            name="Default Project"
        )
        session.add(new_project)
        
        await session.commit()
        print("User, default organization, and project created successfully!")

if __name__ == "__main__":
    asyncio.run(seed_user())
