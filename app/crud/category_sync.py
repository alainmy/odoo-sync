
from typing import Dict
from sqlalchemy.orm import Session
from app.models.admin import CategorySync


def get_categories_map(db: Session) -> Dict[int, int]:
    """
    Devuelve un mapeo Odoo ID -> WooCommerce ID de categorías usando SQLAlchemy.
    """
    rows = db.query(CategorySync.odoo_id, CategorySync.woocommerce_id).all()
    return {odoo_id: wc_id for odoo_id, wc_id in rows}
