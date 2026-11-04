from flask import Flask, render_template, request

from medicine_comparison.config import ATC_GROUPS, DEFAULT_ATC
from medicine_comparison.service import ComparisonService
from medicine_comparison.source import (
    PERIOD_PATTERN,
    SourceError,
    ministry_listings_url,
)


def _format_eur(value, signed: bool = False) -> str:
    if value is None:
        return "—"
    formatted = f"{abs(value):,.2f}"
    prefix = ("−" if value < 0 else "+") if signed else ""
    return f"{prefix}€{formatted}"


def create_app() -> Flask:
    app = Flask(__name__)
    app.extensions["comparison_service"] = ComparisonService()
    app.add_template_filter(_format_eur, "money")
    app.add_template_filter(
        lambda value: _format_eur(value, signed=True), "signed_money"
    )

    @app.get("/")
    def index():
        atc_code = request.args.get("atc", DEFAULT_ATC)
        if atc_code not in ATC_GROUPS:
            atc_code = DEFAULT_ATC
        previous_period = request.args.get("previous", "").strip() or None
        if previous_period is not None and not PERIOD_PATTERN.fullmatch(
            previous_period
        ):
            return "Period must use the YYYYMM format.", 400
        service: ComparisonService = app.extensions["comparison_service"]
        source_url = ministry_listings_url()
        try:
            comparison = service.get_comparison(atc_code, previous_period)
        except SourceError as error:
            return (
                render_template(
                    "index.html",
                    comparison=None,
                    error=str(error),
                    atc_code=atc_code,
                    atc_groups=ATC_GROUPS,
                    previous_period=previous_period,
                    source_url=source_url,
                ),
                503,
            )
        return render_template(
            "index.html",
            comparison=comparison,
            error=None,
            atc_code=atc_code,
            atc_groups=ATC_GROUPS,
            previous_period=previous_period,
            source_url=source_url,
        )

    @app.get("/healthz")
    @app.get("/status")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
