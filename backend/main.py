import logging
import time
from apscheduler.schedulers.background import BackgroundScheduler

from db.models import init_db
from scheduler.jobs import whale_scan_job, position_check_job, daily_report_job, post_mortem_job, set_telegram
from bot.telegram_bot import send_message, start_polling, is_paused
from config import SCAN_INTERVAL, POSITION_CHECK_SECS, PAPER_MODE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("polymind.log"),
    ],
)
logger = logging.getLogger(__name__)


def guarded_whale_scan():
    if is_paused():
        logger.info("Bot paused — skipping whale scan")
        return
    whale_scan_job()


def guarded_position_check():
    position_check_job()


def main():
    logger.info("=" * 50)
    logger.info("PolyMind starting up...")
    logger.info(f"Mode: {'📄 PAPER' if PAPER_MODE else '🔴 LIVE'}")
    logger.info("=" * 50)

    init_db()
    set_telegram(send_message)
    start_polling()

    send_message(
        f"🚀 *PolyMind Online*\n"
        f"Mode: {'📄 PAPER TRADING' if PAPER_MODE else '🔴 LIVE TRADING'}\n"
        f"Whale scan every {SCAN_INTERVAL}s\n"
        f"Position check every {POSITION_CHECK_SECS}s\n"
        f"Type /status for live stats"
    )

    scheduler = BackgroundScheduler()
    scheduler.add_job(guarded_whale_scan,    "interval", seconds=SCAN_INTERVAL,       id="whale_scan")
    scheduler.add_job(guarded_position_check,"interval", seconds=POSITION_CHECK_SECS, id="pos_check")
    scheduler.add_job(post_mortem_job,       "interval", minutes=30,                  id="post_mortem")
    scheduler.add_job(daily_report_job,      "cron",     hour=21, minute=0,           id="daily_report")
    scheduler.start()

    logger.info("Scheduler started. Running first scan...")
    guarded_whale_scan()

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down PolyMind...")
        scheduler.shutdown()
        send_message("⚠️ PolyMind shutting down")


if __name__ == "__main__":
    main()
