"""Create dataset catalog and flexible JSONB row store."""
from alembic import op
from alembic import context
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_catalog"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    tables = set() if context.is_offline_mode() else set(sa.inspect(op.get_bind()).get_table_names())
    if context.is_offline_mode() or "insightforge_datasets" not in tables:
        op.create_table("insightforge_datasets",
        sa.Column("id", sa.CHAR(length=32), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_file", sa.Text(), nullable=False, server_default="original.csv"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    tables = set() if context.is_offline_mode() else set(sa.inspect(op.get_bind()).get_table_names())
    if context.is_offline_mode() or "insightforge_dataset_rows" not in tables:
        op.create_table("insightforge_dataset_rows",
        sa.Column("dataset_id", sa.CHAR(length=32), nullable=False),
        sa.Column("row_number", sa.BigInteger(), nullable=False),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["insightforge_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dataset_id", "row_number"))

def downgrade():
    op.drop_table("insightforge_dataset_rows")
    op.drop_table("insightforge_datasets")
