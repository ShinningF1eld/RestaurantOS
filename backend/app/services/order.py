"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.orders.service import (
    OrderItemCommand as OrderItemCommand,
    CreateOrder as CreateOrder,
    UpdateOrder as UpdateOrder,
    OrderPage as OrderPage,
    OrderRepositoryProtocol as OrderRepositoryProtocol,
    OrderService as OrderService,
)
