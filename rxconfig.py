import reflex as rx

config = rx.Config(
    app_name="PROYECTO_HACKATEC_REGIONAL",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ]
)