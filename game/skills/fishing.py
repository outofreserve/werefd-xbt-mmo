from game.skills.base import Skill, SkillAction, register_skill

FISHING = Skill(
    id="FISHING",
    name="Fishing",
    location_ids=["riverside"],
    actions={
        "shrimp": SkillAction(
            id="shrimp", name="Fish for shrimp", level_req=1, xp=10.0,
            cooldown=4, produces="raw_shrimp", base_success=1.0,
        ),
        "trout": SkillAction(
            id="trout", name="Fish for trout", level_req=20, xp=25.0,
            cooldown=6, produces="raw_trout", base_success=1.0,
        ),
    },
)

register_skill(FISHING)
