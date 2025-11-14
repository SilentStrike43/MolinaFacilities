"""
Send Module - FedEx Sync Management Routes
Admin routes to trigger and monitor FedEx auto-sync
"""

from flask import render_template, request, redirect, url_for, flash, jsonify
from . import bp
from app.modules.auth.security import require_cap, current_user, record_audit
from app.services.fedex.sync import FedExShipmentSync
from app.core.database import get_db_connection
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@bp.route("/admin/sync", methods=["GET", "POST"])
@require_cap("can_send")
def sync_admin():
    """
    FedEx Sync Administration Panel
    Trigger manual syncs and view sync history
    """
    cu = current_user()
    instance_id = cu.get('instance_id')
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "sync_now":
            # Manual sync trigger
            hours_back = int(request.form.get("hours_back", 24))
            
            try:
                from flask import current_app
                sync_service = FedExShipmentSync(current_app.config)
                
                logger.info(f"Manual FedEx sync triggered by {cu.get('username')} for last {hours_back} hours")
                
                result = sync_service.sync_recent_shipments(
                    hours=hours_back,
                    instance_id=instance_id
                )
                
                # Log sync result
                _log_sync_result(cu, hours_back, result)
                
                if result['success']:
                    flash(f"✅ Sync complete! Imported {result['imported']} packages, skipped {result['skipped']} duplicates.", "success")
                    record_audit(cu, "fedex_sync", "send", f"Manual sync: {result['imported']} imported")
                else:
                    flash(f"❌ Sync failed: {result.get('error', 'Unknown error')}", "danger")
                    
            except Exception as e:
                logger.error(f"Manual sync error: {e}", exc_info=True)
                flash(f"❌ Error during sync: {str(e)}", "danger")
            
            return redirect(url_for("send.sync_admin"))
    
    # GET - Show sync history
    sync_history = _get_sync_history()
    sync_stats = _get_sync_stats()
    
    return render_template(
        "send/sync_admin.html",
        active="send-sync",
        sync_history=sync_history,
        sync_stats=sync_stats
    )


@bp.route("/api/sync/trigger", methods=["POST"])
@require_cap("can_send")
def api_sync_trigger():
    """
    API: Trigger FedEx sync via AJAX
    
    POST /send/api/sync/trigger
    Body: {"hours_back": 24}
    """
    try:
        cu = current_user()
        data = request.get_json() or {}
        hours_back = int(data.get("hours_back", 24))
        instance_id = cu.get('instance_id')
        
        from flask import current_app
        sync_service = FedExShipmentSync(current_app.config)
        
        logger.info(f"API sync triggered by {cu.get('username')} for last {hours_back} hours")
        
        result = sync_service.sync_recent_shipments(
            hours=hours_back,
            instance_id=instance_id
        )
        
        # Log sync result
        _log_sync_result(cu, hours_back, result)
        
        if result['success']:
            record_audit(cu, "fedex_sync_api", "send", f"API sync: {result['imported']} imported")
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"API sync error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'imported': 0,
            'skipped': 0
        }), 500


@bp.route("/api/sync/status", methods=["GET"])
@require_cap("can_send")
def api_sync_status():
    """
    API: Get sync status and stats
    
    GET /send/api/sync/status
    """
    try:
        stats = _get_sync_stats()
        history = _get_sync_history(limit=5)
        
        return jsonify({
            'stats': stats,
            'recent_history': [dict(h) for h in history]
        }), 200
        
    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return jsonify({'error': str(e)}), 500


def _log_sync_result(user, hours_back, result):
    """Log sync result to database"""
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fedex_sync_log (
                    instance_id,
                    hours_back,
                    success,
                    imported_count,
                    skipped_count,
                    error_message,
                    triggered_by,
                    triggered_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (
                user.get('instance_id'),
                hours_back,
                result.get('success', False),
                result.get('imported', 0),
                result.get('skipped', 0),
                result.get('error'),
                user.get('id')
            ))
            conn.commit()
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to log sync result: {e}")


def _get_sync_history(limit=20):
    """Get recent sync history"""
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    hours_back,
                    success,
                    imported_count,
                    skipped_count,
                    error_message,
                    triggered_at,
                    u.username as triggered_by_username
                FROM fedex_sync_log fsl
                LEFT JOIN core.users u ON fsl.triggered_by = u.id
                ORDER BY triggered_at DESC
                LIMIT %s
            """, (limit,))
            results = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in results]
    except Exception as e:
        logger.error(f"Error fetching sync history: {e}")
        return []


def _get_sync_stats():
    """Get sync statistics"""
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Total syncs
            cursor.execute("SELECT COUNT(*) as total FROM fedex_sync_log")
            total = cursor.fetchone()['total']
            
            # Successful syncs
            cursor.execute("SELECT COUNT(*) as successful FROM fedex_sync_log WHERE success = TRUE")
            successful = cursor.fetchone()['successful']
            
            # Total imported
            cursor.execute("SELECT SUM(imported_count) as total_imported FROM fedex_sync_log")
            total_imported = cursor.fetchone()['total_imported'] or 0
            
            # Last sync
            cursor.execute("""
                SELECT triggered_at, success, imported_count 
                FROM fedex_sync_log 
                ORDER BY triggered_at DESC 
                LIMIT 1
            """)
            last_sync = cursor.fetchone()
            
            # Auto-populated packages count
            cursor.execute("""
                SELECT COUNT(*) as auto_count 
                FROM package_manifest 
                WHERE auto_populated = TRUE
            """)
            auto_count = cursor.fetchone()['auto_count']
            
            cursor.close()
            
            return {
                'total_syncs': total,
                'successful_syncs': successful,
                'total_imported': total_imported,
                'auto_populated_packages': auto_count,
                'last_sync': dict(last_sync) if last_sync else None,
                'success_rate': round((successful / total * 100) if total > 0 else 0, 1)
            }
    except Exception as e:
        logger.error(f"Error fetching sync stats: {e}")
        return {
            'total_syncs': 0,
            'successful_syncs': 0,
            'total_imported': 0,
            'auto_populated_packages': 0,
            'last_sync': None,
            'success_rate': 0
        }