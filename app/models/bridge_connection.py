"""
Which AI connectors a customer has approved on the website Allow page.

A row is written when the customer presses Allow for a connector ("gst" or "it").
The website can't see when they later disconnect inside Claude / ChatGPT / Gemini,
and the Allow step doesn't say WHICH assistant was used — so "connected" means
"approved on the website", tracked per connector, not per assistant.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db import Base


class BridgeConnection(Base):
    __tablename__ = "bridge_connections"
    __table_args__ = (UniqueConstraint("user_id", "connector", name="uq_bridge_connection_user_connector"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connector = Column(String(10), nullable=False)  # gst | it
    connected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_txn = Column(String(500), nullable=True)


class BridgeConnectorBlock(Base):
    """An admin switched this connector OFF for this customer (everyone else keeps it ON by default)."""

    __tablename__ = "bridge_connector_blocks"
    __table_args__ = (UniqueConstraint("user_id", "connector", name="uq_bridge_block_user_connector"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connector = Column(String(10), nullable=False)  # gst | it
    disabled_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
