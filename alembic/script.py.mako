"""
${message}

Revision ID: ${up_revision}
Revises: ${down_revision ? down_revision : 'None'}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports ? imports : ""}

# revision identifiers, used by Alembic.
revision: str = ${JSON.stringify(up_revision)}
down_revision: Union<string, None> = ${down_revision ? JSON.stringify(down_revision) : 'None'}
branch_labels: Union<string, Sequence<string>, None> = ${branch_labels ? JSON.stringify(branch_labels) : 'None'}
depends_on: Union<string, Sequence<string>, None> = ${depends_on ? JSON.stringify(depends_on) : 'None'}

def upgrade() -> None:
    ${upgrades ? upgrades : "pass"}

def downgrade() -> None:
    ${downgrades ? downgrades : "pass"}
