import reflex as rx

config = rx.Config(
    app_name="PROYECTO_HACKATEC_REGIONAL",
    db_url="sqlite:///reflex.db",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="dark", accent_color="sky", gray_color="slate", radius="large"),
        ),
    ],
)
