"""SQLAlchemy schema for the durable PostgreSQL dataset catalog."""
from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "insightforge_datasets"
    id: Mapped[str] = mapped_column(CHAR(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    active_file: Mapped[str] = mapped_column(Text, nullable=False, default="original.csv")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)


class DatasetRow(Base):
    __tablename__ = "insightforge_dataset_rows"
    dataset_id: Mapped[str] = mapped_column(CHAR(32), ForeignKey("insightforge_datasets.id", ondelete="CASCADE"), primary_key=True)
    row_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    record: Mapped[dict] = mapped_column(JSONB, nullable=False)
