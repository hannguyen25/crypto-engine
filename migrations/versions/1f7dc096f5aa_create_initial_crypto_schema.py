"""create_initial_crypto_schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kích hoạt extension pgcrypto để sinh UUID
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # 1. Bảng users
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_api_secret", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # 2. Bảng intent_logs
    op.create_table(
        "intent_logs",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_prompt", sa.Text(), nullable=False),
        sa.Column("parsed_ir", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_intent_user", "intent_logs", ["user_id"])

    # 3. Bảng execution_orders
    op.create_table(
        "execution_orders",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intent_logs.intent_id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_asset", sa.String(10), nullable=False),
        sa.Column("target_asset", sa.String(10), nullable=False),
        sa.Column("executed_amount", sa.Numeric(28, 10), nullable=True),
        sa.Column("executed_price", sa.Numeric(28, 10), nullable=True),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'FILLED', 'FAILED', 'REJECTED')",
            name="ck_orders_status",
        ),
    )
    op.create_index("idx_orders_idempotency", "execution_orders", ["idempotency_key"])

    # 4. Bảng verifier_audit_trail
    op.create_table(
        "verifier_audit_trail",
        sa.Column("audit_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intent_logs.intent_id"),
            nullable=False,
        ),
        sa.Column("verification_rule", sa.String(100), nullable=False),
        sa.Column("is_passed", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("checked_balance", sa.Numeric(28, 10), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("verifier_audit_trail")
    op.drop_index("idx_orders_idempotency", table_name="execution_orders")
    op.drop_table("execution_orders")
    op.drop_index("idx_intent_user", table_name="intent_logs")
    op.drop_table("intent_logs")
    op.drop_table("users")