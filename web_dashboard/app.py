#!/usr/bin/env python3
"""Flask web dashboard for the Cognitive Assist face recognition system."""

from __future__ import annotations

import base64
import csv
import io
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

# Support both `python -m web_dashboard.app` and `python web_dashboard/app.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from web_dashboard import config as wcfg
    from web_dashboard import queries
else:
    from . import config as wcfg
    from . import queries


def _local_from_iso(iso_value) -> str:
    """ISO UTC -> local display string. Never raises."""
    if not iso_value:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(iso_value)


def create_app(config_overrides: dict | None = None) -> Flask:
    base_dir = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["SECRET_KEY"] = wcfg.SECRET_KEY
    app.config["DATABASE_PATH"] = str(wcfg.DATABASE_PATH)
    app.config["PROJECT_ROOT"] = str(wcfg.PROJECT_ROOT)
    app.config["UNKNOWN_FACES_DIR"] = str(wcfg.UNKNOWN_FACES_DIR)
    app.config["PAGE_SIZE"] = wcfg.PAGE_SIZE
    app.config["AUTH_ENABLED"] = bool(wcfg.USERNAME and wcfg.PASSWORD)
    app.config["CSRF_ENABLED"] = True
    if config_overrides:
        app.config.update(config_overrides)

    if not Path(app.config["DATABASE_PATH"]).is_file():
        print(
            f"[DASHBOARD] Warning: database not found at "
            f"{app.config['DATABASE_PATH']}. Run: python database_setup.py",
            file=sys.stderr,
        )

    def db_path():
        return app.config["DATABASE_PATH"]

    def project_root() -> Path:
        return Path(app.config["PROJECT_ROOT"])

    def unknown_faces_root() -> Path:
        return Path(app.config["UNKNOWN_FACES_DIR"])

    # -------------------------------------------------- template filters

    @app.template_filter("localtime")
    def _filter_localtime(value):
        return _local_from_iso(value)

    @app.template_filter("score")
    def _filter_score(value):
        if value is None:
            return "—"
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return "—"

    @app.template_filter("pretty_name")
    def _filter_pretty_name(value):
        if not value:
            return "—"
        return str(value).replace("_", " ")

    @app.template_filter("slug")
    def _filter_slug(value):
        return (str(value) if value else "").lower().replace("_", "-")

    # ------------------------------------------------------- context

    @app.context_processor
    def _inject_globals():
        return {
            "app_name": "Cognitive Assist",
            "csrf_token": session.get("csrf_token", ""),
        }

    # --------------------------------------------------- auth (optional)

    @app.before_request
    def _ensure_session():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return None

    @app.before_request
    def _require_basic_auth():
        if not app.config.get("AUTH_ENABLED"):
            return None
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Cognitive Assist"'},
            )
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", "replace")
            user, _, pw = decoded.partition(":")
        except Exception:
            user, pw = "", ""
        if user == wcfg.USERNAME and secrets.compare_digest(pw, wcfg.PASSWORD):
            return None
        return Response(
            "Invalid credentials.",
            401,
            {"WWW-Authenticate": 'Basic realm="Cognitive Assist"'},
        )

    @app.before_request
    def _csrf_protect():
        if not app.config.get("CSRF_ENABLED", True):
            return None
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        expected = session.get("csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            return Response("CSRF token missing or invalid.", 403)
        return None

    # -------------------------------------------------------- helpers

    def _image_full_path(relative: str):
        """Resolve a DB image_path to an absolute Path, or None if unsafe."""
        if not relative:
            return None
        candidate = (project_root() / relative).resolve()
        try:
            candidate.relative_to(unknown_faces_root().resolve())
        except (ValueError, OSError):
            return None
        return candidate

    def _read_filters() -> dict:
        return {
            "search": (request.args.get("search") or "").strip(),
            "status": (request.args.get("status") or "").strip().upper(),
            "start_date": (request.args.get("start_date") or "").strip(),
            "end_date": (request.args.get("end_date") or "").strip(),
        }

    def _safe_page() -> int:
        try:
            p = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            p = 1
        return max(1, p)

    # -------------------------------------------------------- routes

    @app.route("/health")
    def health():
        stats = queries.get_summary_stats(db_path())
        return {
            "status": "ok",
            "events": stats["total"],
            "database": app.config["DATABASE_PATH"],
        }

    @app.route("/")
    def dashboard():
        stats = queries.get_summary_stats(db_path())
        recent = queries.get_recent_events(limit=10, db_path=db_path())
        return render_template(
            "dashboard.html",
            active="dashboard",
            stats=stats,
            recent=recent,
        )

    # ------------------------------------------------------ history

    @app.route("/history")
    def history():
        filters = _read_filters()
        page = _safe_page()
        page_size = app.config["PAGE_SIZE"]
        events, total = queries.get_events_paginated(
            filters=filters, page=page, page_size=page_size, db_path=db_path()
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        return render_template(
            "history.html",
            active="history",
            events=events,
            total=total,
            page=page,
            total_pages=total_pages,
            page_size=page_size,
            filters=filters,
        )

    @app.route("/history/export.csv")
    def history_export():
        filters = _read_filters()

        def generate():
            # UTF-8 BOM makes Excel open the file correctly.
            yield "\ufeff"
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow([
                "id", "timestamp", "status", "person_name",
                "similarity_score", "review_status", "error_message",
            ])
            yield buf.getvalue()
            for row in queries.iter_events_for_csv(filters=filters, db_path=db_path()):
                buf.seek(0)
                buf.truncate(0)
                score = row.get("similarity_score")
                writer.writerow([
                    row.get("id", ""),
                    row.get("timestamp", ""),
                    row.get("status", ""),
                    row.get("person_name") or "",
                    "" if score is None else f"{float(score):.6f}",
                    row.get("review_status") or "",
                    (row.get("error_message") or "").replace("\n", " "),
                ])
                yield buf.getvalue()

        filename = datetime.now().strftime("recognition_events_%Y%m%d_%H%M%S.csv")
        return Response(
            generate(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    # -------------------------------------------------- unknown faces

    @app.route("/unknown")
    def unknown_faces():
        filters = {
            "review_status": (request.args.get("review_status") or "").strip().upper(),
        }
        page = _safe_page()
        page_size = app.config["PAGE_SIZE"]
        events, total = queries.get_unknown_faces_paginated(
            filters=filters, page=page, page_size=page_size, db_path=db_path()
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        return render_template(
            "unknown_faces.html",
            active="unknown",
            events=events,
            total=total,
            page=page,
            total_pages=total_pages,
            page_size=page_size,
            filters=filters,
        )

    @app.route("/unknown/<int:event_id>")
    def unknown_detail(event_id):
        event = queries.get_event_by_id(event_id, db_path())
        if not event or event.get("status") != "UNKNOWN":
            abort(404)
        return render_template(
            "unknown_detail.html",
            active="unknown",
            event=event,
            has_image=bool(event.get("image_path")),
        )

    @app.route("/unknown/<int:event_id>/image")
    def unknown_image(event_id):
        event = queries.get_event_by_id(event_id, db_path())
        if not event:
            abort(404)
        full = _image_full_path(event.get("image_path") or "")
        if full is None or not full.is_file():
            abort(404)
        return send_file(str(full), mimetype="image/jpeg", max_age=3600)

    @app.route("/unknown/<int:event_id>/review", methods=["POST"])
    def unknown_review(event_id):
        event = queries.get_event_by_id(event_id, db_path())
        if not event or event.get("status") != "UNKNOWN":
            abort(404)

        new_status = (request.form.get("new_status") or "").strip().upper()
        if new_status not in queries.VALID_REVIEW_STATUSES:
            flash("Invalid review status.", "error")
            return redirect(url_for("unknown_detail", event_id=event_id))

        ok = queries.update_review_status(event_id, new_status, db_path())
        if ok:
            flash(f"Event #{event_id} marked {new_status.lower()}.", "info")
        else:
            flash(f"Could not update event #{event_id}.", "error")
        return redirect(url_for("unknown_detail", event_id=event_id))

    # -------------------------------------------------------- people

    @app.route("/people")
    def people():
        rows = queries.get_people_with_counts(db_path())
        return render_template(
            "people.html",
            active="people",
            people=rows,
        )

    # ------------------------------------------------------ scheduler

    @app.route("/schedule")
    def schedule():
        messages = queries.get_scheduled_messages(db_path())
        return render_template(
            "schedule.html",
            active="schedule",
            messages=messages,
        )

    @app.route("/schedule", methods=["POST"])
    def schedule_add():
        # Check internet connection first
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
        except OSError:
            flash("Cannot schedule: Internet connection required for accurate timekeeping.", "error")
            return redirect(url_for("schedule"))

        time_str = request.form.get("scheduled_time")
        message = request.form.get("message", "").strip()

        if not time_str or not message:
            flash("Time and message are required.", "error")
            return redirect(url_for("schedule"))

        try:
            # HTML datetime-local gives us "2026-10-27T15:30"
            dt_local = datetime.strptime(time_str, "%Y-%m-%dT%H:%M")
            # Attach local timezone and convert to UTC
            dt_utc = dt_local.astimezone().astimezone(timezone.utc)
            utc_iso = dt_utc.isoformat(timespec="milliseconds")
        except ValueError:
            flash("Invalid date/time format.", "error")
            return redirect(url_for("schedule"))

        if queries.add_scheduled_message(utc_iso, message, db_path()):
            flash("Message scheduled successfully.", "info")
        else:
            flash("Failed to schedule message.", "error")
            
        return redirect(url_for("schedule"))

    @app.route("/schedule/<int:msg_id>/cancel", methods=["POST"])
    def schedule_cancel(msg_id):
        if queries.cancel_scheduled_message(msg_id, db_path()):
            flash(f"Message #{msg_id} cancelled.", "info")
        else:
            flash(f"Could not cancel message #{msg_id}.", "error")
        return redirect(url_for("schedule"))

    # -------------------------------------------------- error handlers

    @app.errorhandler(404)
    def _not_found(_exc):
        return render_template("404.html", active=""), 404

    @app.errorhandler(500)
    def _server_error(_exc):
        return render_template("500.html", active=""), 500

    return app


def main() -> None:
    app = create_app()
    host = wcfg.HOST
    port = wcfg.PORT
    notes = []
    if app.config.get("AUTH_ENABLED"):
        notes.append("basic auth ON")
    if not app.config.get("CSRF_ENABLED"):
        notes.append("CSRF OFF")
    suffix = f" ({', '.join(notes)})" if notes else ""
    print(f"[DASHBOARD] Serving on http://{host}:{port}{suffix} (debug=False)")
    print(f"[DASHBOARD] Database: {app.config['DATABASE_PATH']}")
    app.run(
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
