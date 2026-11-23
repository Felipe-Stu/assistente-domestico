"""Skills do assistente: uma pasta por capacidade (ver skills/README.md)."""
from core.skills.catalogo import (  # noqa: F401
    PASTA_SKILLS,
    Catalogo,
    Gatilho,
    Skill,
    SkillInvalidaError,
    carregar_catalogo,
    carregar_skill,
    obter_catalogo,
    recarregar_catalogo,
)
