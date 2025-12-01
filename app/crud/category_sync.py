
from typing import Dict
from sqlalchemy.orm import Session
from app.models.admin import CategroySync


def get_categories_map(db: Session) -> Dict[int, int]:
    """
    Devuelve un mapeo Odoo ID -> WooCommerce ID de categorías usando SQLAlchemy.
    """
    rows = db.query(CategroySync.odoo_id, CategroySync.woocommerce_id).all()
    return {odoo_id: wc_id for odoo_id, wc_id in rows}
