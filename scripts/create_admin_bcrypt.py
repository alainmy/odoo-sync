"""
Script to create admin user using bcrypt from security.py
"""
import sys
sys.path.insert(0, '/app')

from app.db.session import SessionLocal
from app.models.user_model import User
from app.core.security import get_password_hash

def create_admin_user():
    db = SessionLocal()
    try:
        # Delete existing admin if exists
        existing = db.query(User).filter(User.username == 'admin').first()
        if existing:
            db.delete(existing)
            db.commit()
            print("Usuario admin existente eliminado")
        
        # Create new admin user with bcrypt hash
        hashed_password = get_password_hash('admin123')
        
        admin = User(
            username='admin',
            email='admin@example.com',
            full_name='Administrator',
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=True
        )
        
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        print("✅ Usuario admin creado exitosamente!")
        print(f"   Username: admin")
        print(f"   Password: admin123")
        print(f"   ID: {admin.id}")
        print(f"   Hash length: {len(admin.hashed_password)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin_user()
