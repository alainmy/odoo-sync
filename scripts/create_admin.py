"""
Script to create admin user for the application
"""
import sys
sys.path.insert(0, '/app')

from app.db.session import SessionLocal
from app.models.user_model import User
from passlib.hash import bcrypt

def create_admin_user():
    db = SessionLocal()
    try:
        # Check if admin user already exists
        existing_user = db.query(User).filter(User.username == 'admin').first()
        if existing_user:
            print("✅ Admin user already exists!")
            print(f"   Username: {existing_user.username}")
            print(f"   Email: {existing_user.email}")
            return
        
        # Create admin user using passlib bcrypt (same as security.py)
        password = "admin123"
        hashed = bcrypt.using(rounds=12).hash(password)
        
        admin = User(
            username='admin',
            email='admin@example.com',
            full_name='Administrator',
            hashed_password=hashed,
            is_active=True,
            is_superuser=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        print("✅ Admin user created successfully!")
        print(f"   Username: admin")
        print(f"   Email: admin@example.com")
        print(f"   Password: admin123")
        print(f"   ID: {admin.id}")
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin_user()
