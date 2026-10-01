from game.skills.base import Skill, SkillAction, register_skill

MINING = Skill(
    id="MINING",
    name="Mining",
    location_ids=["quarry"],
    actions={
        "copper": SkillAction(
            id="copper", name="Mine copper ore", level_req=1, xp=10.0,
            cooldown=4, produces="copper_ore", base_success=1.0,
        ),
        "tin": SkillAction(
            id="tin", name="Mine tin ore", level_req=1, xp=10.0,
            cooldown=4, produces="tin_ore", base_success=1.0,
        ),
        "iron": SkillAction(
            id="iron", name="Mine iron ore", level_req=15, xp=35.0,
            cooldown=7, produces="iron_ore", base_success=1.0,
        ),
    },
)

register_skill(MINING)
