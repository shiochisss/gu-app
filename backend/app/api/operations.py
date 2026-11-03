from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request

from app.api.orders import DB, Customer, raw_body, schedule
from app.api.staff_stock import Staff
from app.models import Store
from app.schemas.operations import (
    AcceptanceInput,
    DelayInput,
    HandoverInput,
    HandoverResult,
    HoursInput,
    ShortageInput,
    StaffOrderDetail,
    StaffOrderList,
    StaffStore,
    Verification,
    VerifyInput,
    VersionInput,
)
from app.schemas.ordering import OrderDetail
from app.services import (
    lifecycle,
    order_actions,
    order_queries,
    pickup_verification,
    staff_orders,
    staff_store,
)
from app.services.stock_pos import timestamp

router = APIRouter(prefix="/api/v1", tags=["preparation, pickup and store operations"])
Key = Annotated[str | None, Header(alias="Idempotency-Key")]


def action(request, tasks, db, user, order_id, data, key, mutate, *, store_id=None, render=None):
    result = order_actions.execute(
        db,
        request,
        user,
        key,
        str(order_id),
        data,
        mutate,
        render
        or (
            staff_orders.staff_detail
            if store_id
            else lambda db, order: order_queries.detail(db, order, request.app.state.settings)
        ),
        store_id,
    )
    schedule(request, tasks)
    return result


@router.get("/staff/orders", response_model=StaffOrderList)
def orders(
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    tab: Literal["ACTIVE", "DELAYED", "ACTION_REQUIRED", "READY", "EXPIRED", "DONE"],
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    result = staff_orders.list_orders(
        db,
        identity[1],
        tab,
        page,
        pageSize,
        request.app.state.settings,
        request.app.state.clock.now(),
    )
    schedule(request, tasks)
    return result


@router.get("/staff/orders/{order_id}", response_model=StaffOrderDetail)
def detail(order_id: UUID, request: Request, tasks: BackgroundTasks, db: DB, identity: Staff):
    order, _ = lifecycle.locked_order(db, str(order_id), *identity)
    order_queries.sync_time(db, order, request.app.state.settings, request.app.state.clock.now())
    result = staff_orders.staff_detail(db, order)
    db.commit()
    schedule(request, tasks)
    return result


@router.post(
    "/staff/orders/{order_id}/preparation/start", response_model=StaffOrderDetail, dependencies=[]
)
def start(
    order_id: UUID,
    data: VersionInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    order, payment = lifecycle.locked_order(db, str(order_id), *identity)
    lifecycle.check_version(
        db, order, data, request.app.state.settings, request.app.state.clock.now()
    )
    lifecycle.start(
        db,
        order,
        payment,
        identity[0],
        data,
        request.app.state.settings,
        request.app.state.clock.now(),
    )
    result = staff_orders.staff_detail(db, order)
    db.commit()
    schedule(request, tasks)
    return result


@router.post(
    "/staff/orders/{order_id}/shortages",
    response_model=StaffOrderDetail,
    dependencies=[Depends(raw_body)],
)
def shortage(
    order_id: UUID,
    data: ShortageInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return action(
        request,
        tasks,
        db,
        identity[0],
        order_id,
        data,
        key,
        lifecycle.register_shortage,
        store_id=identity[1],
    )


@router.post(
    "/staff/orders/{order_id}/delay",
    response_model=StaffOrderDetail,
    dependencies=[Depends(raw_body)],
)
def delay(
    order_id: UUID,
    data: DelayInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return action(
        request,
        tasks,
        db,
        identity[0],
        order_id,
        data,
        key,
        lifecycle.register_delay,
        store_id=identity[1],
    )


@router.post(
    "/staff/orders/{order_id}/ready",
    response_model=StaffOrderDetail,
    dependencies=[Depends(raw_body)],
)
def ready(
    order_id: UUID,
    data: VersionInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return action(
        request,
        tasks,
        db,
        identity[0],
        order_id,
        data,
        key,
        lifecycle.prepare_capture,
        store_id=identity[1],
    )


@router.post(
    "/staff/orders/{order_id}/return-to-stock",
    response_model=StaffOrderDetail,
    dependencies=[Depends(raw_body)],
)
def returned(
    order_id: UUID,
    data: VersionInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return action(
        request,
        tasks,
        db,
        identity[0],
        order_id,
        data,
        key,
        lifecycle.return_to_stock,
        store_id=identity[1],
    )


@router.post(
    "/orders/{order_id}/cancel", response_model=OrderDetail, dependencies=[Depends(raw_body)]
)
def cancel(
    order_id: UUID,
    data: VersionInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    user: Customer,
    key: Key = None,
):
    return action(request, tasks, db, user, order_id, data, key, lifecycle.cancel_customer)


@router.post(
    "/orders/{order_id}/pickup-token/reissue",
    response_model=OrderDetail,
    dependencies=[Depends(raw_body)],
)
def reissue(
    order_id: UUID,
    data: VersionInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    user: Customer,
    key: Key = None,
):
    return action(request, tasks, db, user, order_id, data, key, lifecycle.reissue)


@router.post("/staff/pickups/verify", response_model=Verification)
def verify(data: VerifyInput, request: Request, tasks: BackgroundTasks, db: DB, identity: Staff):
    result = pickup_verification.verify(db, request.app, *identity, data)
    schedule(request, tasks)
    return result


def handover_response(db, order):
    return dict(
        orderId=order.id,
        orderNumber=order.order_number,
        status=order.status,
        pickedUpAt=timestamp(order.picked_up_at),
    )


@router.post(
    "/staff/orders/{order_id}/handover",
    response_model=HandoverResult,
    dependencies=[Depends(raw_body)],
)
def handover(
    order_id: UUID,
    data: HandoverInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return action(
        request,
        tasks,
        db,
        identity[0],
        order_id,
        data,
        key,
        lifecycle.handover,
        store_id=identity[1],
        render=handover_response,
    )


@router.get("/staff/store", response_model=StaffStore)
def store_info(request: Request, db: DB, identity: Staff):
    return staff_store.info(db, db.get(Store, identity[1]), request.app.state.clock.now())


@router.put("/staff/store/acceptance", response_model=StaffStore)
def acceptance(data: AcceptanceInput, request: Request, db: DB, identity: Staff):
    return staff_store.acceptance(db, *identity, data, request.app.state.clock.now())


@router.put("/staff/store/business-hours/{day}", response_model=StaffStore)
def hours(day: date, data: HoursInput, request: Request, db: DB, identity: Staff):
    return staff_store.change_hours(db, *identity, day, data, request.app.state.clock.now())
