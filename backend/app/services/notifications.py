import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from time import perf_counter

from sqlalchemy import select

from app.models import Notification, OrderItem, Store, User
from app.payments.budget import timeout
from app.services.business_calendar import JST

FOOTER = "このメールは送信時点の情報です。最新の状況は注文詳細でご確認ください。"


def date_text(value):
    local = value.astimezone(JST)
    return f"{local.month}月{local.day}日 {local:%H:%M}"


def enqueue(db, order, kind, settings, now, *, reason=None):
    store = db.get(Store, order.store_id)
    user = db.get(User, order.purchaser_id)
    url = str(settings.frontend_base_url).rstrip("/") + "/orders/" + order.id
    if kind == "ORDER_ACCEPTED":
        subject = "ご注文を受け付けました"
        text = (
            f"{store.name}でのご注文を受け付けました。"
            f"準備完了予定：{date_text(order.original_ready_at)}。合計：¥{order.ordered_amount_yen:,}。"
            f"受取期限は準備完了日の1週間後の閉店時刻です。"
            f"最新の状況は注文詳細でご確認ください：{url}"
        )
    elif kind == "READY":
        subject = "商品の準備ができました"
        text = (
            f"{store.name}で商品をお受け取りいただけます。"
            f"受取期限：{date_text(order.pickup_deadline_at)}。確定金額：¥{order.captured_amount_yen:,}。"
            f"注文詳細のQRコードを店員にご提示ください（QRを渡した方も受け取れます）：{url}"
        )
    elif kind == "SHORTAGE_CHANGED":
        subject = "欠品により注文内容が変わりました"
        items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        missing = "、".join(
            f"{x.product_name} {x.color_name}/{x.size} × {x.shortage_quantity}"
            for x in items
            if x.shortage_quantity
        )
        amount = sum(x.unit_price_yen * (x.ordered_quantity - x.shortage_quantity) for x in items)
        text = (
            f"次の商品が用意できませんでした：{missing}。ご希望に従い、用意できた商品だけを購入します。"
            f"変更後の金額：¥{amount:,}：{url}"
        )
    elif kind == "CANCELLED":
        subject = "ご注文を取り消しました"
        handling = (
            "全額を返金します。" if order.captured_amount_yen else "カードの利用枠を解放します。"
        )
        text = f"取消理由：{reason}。{handling}：{url}"
    elif kind == "DELAYED":
        subject = "準備が遅れています"
        ready = date_text(order.updated_ready_at) if order.updated_ready_at else "確認中"
        text = (
            f"理由：{reason}。新しい予定：{ready}。"
            f"受け取り前であれば、注文詳細から無料で取り消せます：{url}"
        )
    elif kind == "EXPIRED":
        subject = "受取期限を過ぎました"
        text = (
            f"受取期限（{date_text(order.pickup_deadline_at)}）を過ぎました。"
            "店舗が商品を棚に戻すまではお受け取りいただけます。"
            f"棚に戻した後は受け取れず、代金は返金されません：{url}"
        )
    else:
        raise ValueError("unsupported notification template")
    row = Notification(
        order_id=order.id,
        user_id=user.id,
        type=kind,
        recipient_email=user.email,
        subject=f"【Pickup App】{subject}（{order.order_number}）",
        body_text=text + "\n\n" + FOOTER,
        status="PENDING",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
    )
    db.add(row)


def smtp_send(settings, row):
    message = EmailMessage()
    message["From"] = settings.mail_from.get_secret_value()
    message["To"] = row.recipient_email
    message["Subject"] = row.subject
    message.set_content(row.body_text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout()) as connection:
        connection.starttls(context=ssl.create_default_context())
        connection.sock.settimeout(timeout())
        connection.login(
            settings.smtp_username.get_secret_value(), settings.smtp_password.get_secret_value()
        )
        connection.sock.settimeout(timeout())
        connection.send_message(message)


def dispatch(factory, settings, clock, sender=smtp_send, *, limit=100, deadline=float("inf")):
    # SKIP LOCKED prevents BackgroundTasks and the later J-04 worker from claiming
    # the same row. SMTP work stays separate from the business transaction.
    with factory() as db:
        ids = db.scalars(
            select(Notification.id)
            .where(Notification.status == "PENDING", Notification.next_attempt_at <= clock.now())
            .order_by(Notification.created_at, Notification.id)
            .limit(limit)
        ).all()
    processed = 0
    for ident in ids:
        if perf_counter() >= deadline:
            break
        with factory() as db:
            row = db.scalar(
                select(Notification)
                .where(
                    Notification.id == ident,
                    Notification.status == "PENDING",
                    Notification.next_attempt_at <= clock.now(),
                )
                .with_for_update(skip_locked=True)
            )
            if row is None:
                continue
            row.attempt_count += 1
            processed += 1
            try:
                if settings.mail_mode == "smtp":
                    sender(settings, row)
                row.status = "SENT" if settings.mail_mode == "smtp" else "SIMULATED"
                row.sent_at, row.last_error_code = clock.now(), None
            except Exception as exc:
                row.last_error_code = type(exc).__name__[:64]
                row.next_attempt_at = clock.now() + timedelta(minutes=2 ** (row.attempt_count - 1))
                if row.attempt_count >= 5:
                    row.status = "FAILED"
            db.commit()

    return processed
