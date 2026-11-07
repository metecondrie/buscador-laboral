"""Catálogo de proveedores y modelos de IA.

Cada entrada está respaldada por la documentación oficial consultada el
2026-11-06 (ver `docs/ia-proveedores.md`). Los identificadores se escriben tal
como los publica cada API; no se agregan modelos por suposición.

Tres familias de transporte:

- `gemini`: cuerpo `contents`/`systemInstruction`, clave por query string.
- `openai`: compatible con chat completions (Groq, DeepSeek, OpenRouter, local).
- `cloudflare`: Workers AI, mismo formato OpenAI bajo `/accounts/{id}/ai/v1`.

Ningún modelo se usa sin comprobar disponibilidad: `verificado` indica si el
identificador fue contrastado contra la documentación o contra la API real.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Modelo:
    proveedor: str
    id: str
    etiqueta: str
    nivel: str                  # rapido | equilibrado | profundo
    familia: str                # gemini | openai | cloudflare
    contexto: int = 0
    usd_entrada_1m: float = 0.0
    usd_salida_1m: float = 0.0
    dentro_cuota_gratuita: bool = True
    verificado: bool = True
    notas: str = ""


@dataclass(frozen=True)
class Proveedor:
    clave: str
    nombre: str
    familia: str
    endpoint: str
    variable_clave: str
    objetivo_credencial: str
    requiere_pago: bool = False
    permite_prueba: bool = True
    modelos: tuple[Modelo, ...] = ()
    limites: dict[str, int] = field(default_factory=dict)
    notas: str = ""
    docs: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def modelo(self, identificador: str) -> Modelo | None:
        for candidato in self.modelos:
            if candidato.id == identificador:
                return candidato
        return None

    @property
    def modelo_por_defecto(self) -> str:
        return self.modelos[0].id if self.modelos else ""


GEMINI = Proveedor(
    clave="gemini",
    nombre="Google Gemini (AI Studio)",
    familia="gemini",
    endpoint="https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
    variable_clave="GEMINI_API_KEY",
    objetivo_credencial="BuscadorLaboral/gemini",
    modelos=(
        Modelo("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "rapido", "gemini",
               contexto=1_000_000,
               notas="Nivel gratuito disponible; los topes exactos se leen en AI Studio."),
        Modelo("gemini", "gemini-3.6-flash", "Gemini 3.6 Flash", "equilibrado", "gemini",
               contexto=1_000_000, notas="Estable según la tabla oficial de modelos."),
        Modelo("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", "profundo", "gemini",
               contexto=1_000_000, notas="Estable; reemplaza a 2.5 Pro desde el 01/12/2026."),
    ),
    limites={"rpm": 10, "rpd": 250, "tpm": 250_000},
    notas="El nivel gratuito es por proyecto y se reinicia a medianoche del Pacífico. "
          "Los topes exactos dependen del proyecto: confirmalos en AI Studio.",
    docs="https://ai.google.dev/gemini-api/docs/models · https://ai.google.dev/gemini-api/docs/rate-limits",
)

GROQ = Proveedor(
    clave="groq",
    nombre="Groq",
    familia="openai",
    endpoint="https://api.groq.com/openai/v1/chat/completions",
    variable_clave="GROQ_API_KEY",
    objetivo_credencial="BuscadorLaboral/groq",
    modelos=(
        Modelo("groq", "openai/gpt-oss-20b", "GPT-OSS 20B (Groq)", "rapido", "openai",
               contexto=131_072, notas="Nivel gratuito: 30 RPM · 1.000 RPD · 8K TPM · 200K TPD."),
        Modelo("groq", "openai/gpt-oss-120b", "GPT-OSS 120B (Groq)", "equilibrado", "openai",
               contexto=131_072, notas="Mismos topes gratuitos que el 20B."),
    ),
    limites={"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
    notas="Plan gratuito sin tarjeta. Al agotar RPD devuelve 429 con retry-after.",
    docs="https://console.groq.com/docs/rate-limits",
)

CLOUDFLARE = Proveedor(
    clave="cloudflare",
    nombre="Cloudflare Workers AI",
    familia="cloudflare",
    endpoint="https://api.cloudflare.com/client/v4/accounts/{cuenta}/ai/v1/chat/completions",
    variable_clave="CLOUDFLARE_API_TOKEN",
    objetivo_credencial="BuscadorLaboral/cloudflare",
    modelos=(
        Modelo("cloudflare", "@cf/openai/gpt-oss-20b", "GPT-OSS 20B (Workers AI)", "rapido", "cloudflare",
               contexto=131_072, usd_entrada_1m=0.20, usd_salida_1m=0.30,
               notas="18.182 / 27.273 neuronas por millón de tokens."),
        Modelo("cloudflare", "@cf/openai/gpt-oss-120b", "GPT-OSS 120B (Workers AI)", "equilibrado", "cloudflare",
               contexto=131_072, usd_entrada_1m=0.35, usd_salida_1m=0.75,
               notas="31.818 / 68.182 neuronas por millón de tokens."),
    ),
    limites={"rpd": 0},
    notas="Asignación gratuita de 10.000 neuronas por día, sin tarjeta. Requiere el "
          "identificador de cuenta además del token.",
    docs="https://developers.cloudflare.com/workers-ai/platform/pricing/",
    extra={"cuenta_variable": "CLOUDFLARE_ACCOUNT_ID"},
)

DEEPSEEK = Proveedor(
    clave="deepseek",
    nombre="DeepSeek",
    familia="openai",
    endpoint="https://api.deepseek.com/chat/completions",
    variable_clave="DEEPSEEK_API_KEY",
    objetivo_credencial="BuscadorLaboral/deepseek",
    requiere_pago=True,
    modelos=(
        Modelo("deepseek", "deepseek-flash", "DeepSeek V4.1 Flash", "profundo", "openai",
               contexto=1_000_000, usd_entrada_1m=0.30, usd_salida_1m=1.20,
               dentro_cuota_gratuita=False,
               notas="Sin nivel gratuito. Precio de hora pico; fuera de pico es la mitad."),
    ),
    limites={},
    notas="Sólo último recurso y con autorización expresa de gasto. Un saldo disponible "
          "no es autorización.",
    docs="https://api-docs.deepseek.com/quick_start/pricing",
)

PROVEEDORES: dict[str, Proveedor] = {
    p.clave: p for p in (GEMINI, GROQ, CLOUDFLARE, DEEPSEEK)
}

# Cascada predeterminada: sólo Gemini, de rápido a profundo.
# Groq, Cloudflare y DeepSeek siguen en el catálogo pero desactivados: se
# conservan para más adelante, no se usan ni se piden credenciales para ellos.
CASCADA_POR_DEFECTO = (
    "gemini:gemini-3.5-flash-lite",
    "gemini:gemini-3.6-flash",
    "gemini:gemini-3.8-flash",
)

PROVEEDORES_ACTIVOS = frozenset({"gemini"})

ESTADOS_CREDENCIAL = ("ausente", "presente", "verificada", "invalida")


def obtener(clave: str) -> Proveedor | None:
    return PROVEEDORES.get((clave or "").strip().lower())


def parsear(entrada: str) -> tuple[Proveedor, Modelo] | None:
    """`proveedor:modelo` → (Proveedor, Modelo) o None si no existe."""
    if not entrada or ":" not in entrada:
        return None
    clave, identificador = entrada.split(":", 1)
    proveedor = obtener(clave)
    if proveedor is None:
        return None
    modelo = proveedor.modelo(identificador)
    if modelo is None:
        return None
    return proveedor, modelo


def catalogo() -> list[dict]:
    """Vista plana para la interfaz: un renglón por modelo."""
    filas = []
    for proveedor in PROVEEDORES.values():
        for modelo in proveedor.modelos:
            filas.append({
                "proveedor": proveedor.clave,
                "proveedor_nombre": proveedor.nombre,
                "modelo": modelo.id,
                "modelo_nombre": modelo.etiqueta,
                "nivel": modelo.nivel,
                "contexto": modelo.contexto,
                "gratuito": modelo.dentro_cuota_gratuita,
                "requiere_pago": proveedor.requiere_pago,
                "verificado": modelo.verificado,
                "notas": modelo.notas,
                "referencia": f"{proveedor.clave}:{modelo.id}",
            })
    return filas
