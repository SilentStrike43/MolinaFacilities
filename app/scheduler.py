"""
Background Job Scheduler
Handles periodic tasks like tracking updates and FedEx sync
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


def update_all_tracking(app):
    """
    Background job: Update tracking status for all active shipments
    """
    with app.app_context():
        try:
            from app.services.tracking.tracker import TrackingService
            from app.core.database import get_db_connection
            
            logger.info("Starting scheduled tracking update...")
            
            # Get all packages that need tracking update
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT id, tracking_number, carrier
                    FROM package_manifest
                    WHERE tracking_number IS NOT NULL
                    AND tracking_status NOT IN ('DELIVERED', 'RETURN_TO_SENDER')
                    AND (
                        last_tracked_at IS NULL OR
                        last_tracked_at < NOW() - INTERVAL '%s hours'
                    )
                    ORDER BY created_at DESC
                    LIMIT 100
                """, (app.config.get('TRACKING_UPDATE_INTERVAL', 4),))
                
                packages = cursor.fetchall()
                cursor.close()
            
            if not packages:
                logger.info("No packages need tracking update")
                return
            
            # Initialize tracking service
            tracker = TrackingService(app.config)
            
            updated = 0
            failed = 0
            
            for pkg in packages:
                try:
                    result = tracker.track(pkg['tracking_number'], pkg['carrier'])
                    
                    if result.success:
                        # Update package with new tracking info
                        with get_db_connection("send") as conn:
                            cursor = conn.cursor()
                            
                            cursor.execute("""
                                UPDATE package_manifest
                                SET
                                    tracking_status = %s,
                                    tracking_status_description = %s,
                                    estimated_delivery_date = %s,
                                    actual_delivery_date = %s,
                                    delivered_to = %s,
                                    delivery_signature = %s,
                                    delivery_location = %s,
                                    last_tracked_at = CURRENT_TIMESTAMP,
                                    tracking_last_updated = CURRENT_TIMESTAMP,
                                    tracking_error = NULL
                                WHERE id = %s
                            """, (
                                result.status,
                                result.status_description,
                                result.estimated_delivery,
                                result.actual_delivery,
                                result.delivered_to,
                                result.signature,
                                result.location,
                                pkg['id']
                            ))
                            
                            # Save tracking events
                            for event in result.events:
                                cursor.execute("""
                                    INSERT INTO tracking_events (
                                        package_id,
                                        event_timestamp,
                                        status_code,
                                        status_description,
                                        location_full,
                                        event_details
                                    ) VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (package_id, event_timestamp, status_code) DO NOTHING
                                """, (
                                    pkg['id'],
                                    event.get('timestamp'),
                                    event.get('status'),
                                    event.get('description'),
                                    event.get('location'),
                                    None
                                ))
                            
                            conn.commit()
                            cursor.close()
                        
                        updated += 1
                    else:
                        # Log error
                        with get_db_connection("send") as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE package_manifest
                                SET
                                    tracking_error = %s,
                                    last_tracked_at = CURRENT_TIMESTAMP
                                WHERE id = %s
                            """, (result.error, pkg['id']))
                            conn.commit()
                            cursor.close()
                        
                        failed += 1
                        
                except Exception as e:
                    logger.error(f"Error updating tracking for {pkg['tracking_number']}: {str(e)}")
                    failed += 1
            
            logger.info(f"Tracking update complete: {updated} updated, {failed} failed")
            
        except Exception as e:
            logger.error(f"Tracking update job failed: {str(e)}")


def sync_fedex_shipments(app):
    """
    Background job: Sync FedEx shipments from account
    """
    with app.app_context():
        try:
            from app.services.fedex.sync import FedExShipmentSync
            
            if not app.config.get('FEDEX_SYNC_ENABLED'):
                return
            
            logger.info("Starting FedEx auto-sync...")
            
            sync_service = FedExShipmentSync(app.config)
            result = sync_service.sync_recent_shipments(
                hours=1,
                instance_id=None
            )
            
            if result['success']:
                logger.info(f"FedEx sync complete: {result['imported']} imported, {result['skipped']} skipped")
            else:
                logger.error(f"FedEx sync failed: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"FedEx sync job failed: {str(e)}")


def init_scheduler(app):
    """
    Initialize background scheduler with Flask app context
    
    Args:
        app: Flask application instance
    """
    global scheduler
    
    if scheduler is not None:
        logger.warning("Scheduler already initialized")
        return scheduler
    
    scheduler = BackgroundScheduler(daemon=True)
    
    # Add tracking update job
    tracking_interval = app.config.get('TRACKING_UPDATE_INTERVAL', 4)
    scheduler.add_job(
        func=lambda: update_all_tracking(app),
        trigger=IntervalTrigger(hours=tracking_interval),
        id='update_tracking',
        name='Update package tracking status',
        replace_existing=True
    )
    logger.info(f"✅ Scheduled tracking updates every {tracking_interval} hours")
    
    # Add FedEx sync job (if enabled)
    if app.config.get('FEDEX_SYNC_ENABLED'):
        fedex_interval = app.config.get('FEDEX_SYNC_INTERVAL', 30)
        scheduler.add_job(
            func=lambda: sync_fedex_shipments(app),
            trigger=IntervalTrigger(minutes=fedex_interval),
            id='fedex_sync',
            name='Sync FedEx shipments',
            replace_existing=True
        )
        logger.info(f"✅ Scheduled FedEx sync every {fedex_interval} minutes")
    
    scheduler.start()
    logger.info("✅ Background scheduler started successfully")
    
    return scheduler


def shutdown_scheduler():
    """Gracefully shutdown scheduler"""
    global scheduler
    
    if scheduler is not None:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")
        scheduler = None