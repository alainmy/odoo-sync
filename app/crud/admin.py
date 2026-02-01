from app.models.admin import ProductSync
from app.schemas.admin import ProductSyncCreate
from sqlalchemy.orm import Session
from app.models.admin import Admin, CategorySync
from app.schemas.admin import AdminCreate, CategorySyncCreate, CategorySync


# CRUD para ProductSync
def save_product_sync(db: Session, item: ProductSyncCreate):
    db_item = ProductSync(odoo_id=item.odoo_id, woocommerce_id=item.woocommerce_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_product_sync(db: Session, db_item: ProductSync, item: ProductSyncCreate):
    db_item.odoo_id = item.odoo_id
    db_item.woocommerce_id = item.woocommerce_id
    db.commit()
    db.refresh(db_item)
    return db_item


def get_product_sync_by_odoo_id(db: Session, item_id: int,
                                instance_id: int):
    return db.query(ProductSync).filter(ProductSync.odoo_id == item_id,
                                        ProductSync.instance_id == instance_id).first()



def get_admin(db: Session, item_id: int):
    return db.query(Admin).filter(Admin.id == item_id).first()


def create_admin(db: Session, item: AdminCreate):
    db_item = Admin(name=item.name, description=item.description)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_admin(db: Session, db_item: Admin, item: AdminCreate):
    db_item.name = item.name
    db_item.description = item.description
    db.commit()
    db.refresh(db_item)
    return db_item


def delete_admin(db: Session, item_id: int):
    db_item = db.query(Admin).filter(Admin.id == item_id).first()
    db.delete(db_item)
    db.commit()
    return db_item


def save_categroy_sync(db: Session, item: CategorySyncCreate):
    db_item = CategorySync(odoo_id=item.odoo_id,
                           woocommerce_id=item.woocommerce_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_categroy_sync(db: Session, db_item: CategorySync, item: CategorySyncCreate):
    db_item.odoo_id = item.odoo_id
    db_item.woocommerce_id = item.woocommerce_id
    db.commit()
    db.refresh(db_item)
    return db_item


def delete_categroy_sync(db: Session, item_id: int):
    db_item = db.query(CategorySync).filter(CategorySync.id == item_id).first()
    db.delete(db_item)
    db.commit()
    return db_item


def get_categroy_by_odoo_id(db: Session, item_id: int):
    return db.query(CategorySync).filter(CategorySync.odoo_id == item_id).first()
