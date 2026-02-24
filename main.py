"""
╔══════════════════════════════════════════╗
║   NEON DRIFT v2  //  시민 로그           ║
║   터미널 기반 사이버펑크 오픈월드 RPG    ║
╠══════════════════════════════════════════╣
║  실행: python3 neon_drift_v2.py          ║
║  요구: pip install blessed               ║
║  이동: WASD / 방향키                     ║
║  행동: E(상호작용) I(인벤토리) Q(종료)   ║
║        J(퀘스트)  C(캐릭터) S(저장)      ║
╚══════════════════════════════════════════╝
"""
import random, time, math, json, os, sys
from blessed import Terminal
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import deque
from enum import Enum, auto
from copy import deepcopy

# ═══════════════════════════════════════════
#  § 1. 상수 & 기본 설정
# ═══════════════════════════════════════════
MAP_W, MAP_H   = 100, 100
VIEW_W, VIEW_H = 55, 28
PANEL_X        = VIEW_W + 2
PANEL_W        = 24
BASE_FOV       = 8
TICK           = 0.07
DAY_LEN        = 240          # 초 기준 하루
SAVE_FILE      = "neon_save.json"

# 타일 문자
T_FLOOR   = '·'; T_WALL  = '█'; T_ROAD   = '░'
T_BUILD   = '▓'; T_NEON  = '*'; T_ERROR  = '%'
T_PLAYER  = '@'; T_NPC   = '?'; T_MERCH  = '§'
T_ENEMY_D = '∆'; T_ENEMY_G = '&'; T_ENEMY_E = '%'
T_DOOR    = '▐'; T_TERM  = '⌨'; T_CCTV   = 'Ω'
T_ITEM    = 'i'; T_DARK  = '.' ; T_CHEST  = '□'


# ═══════════════════════════════════════════
#  § 2. 열거형
# ═══════════════════════════════════════════
class Zone(Enum):
    NEON_COMMERCIAL = 0
    RESIDENTIAL     = 1
    LOW_SIGNAL      = 2
    INDUSTRIAL      = 3
    ROOFTOP_NETWORK = 4

class Weather(Enum):
    CLEAR = "맑음"; RAIN = "비"; HEAVY = "폭우"

class ItemGrade(Enum):
    COMMON    = ("일반",  "white")
    RARE      = ("희귀",  "cyan")
    LEGENDARY = ("전설",  "yellow")

class StatusEffect(Enum):
    NONE     = auto(); POISONED = auto()
    STUNNED  = auto(); BURNED   = auto()
    SHOCKED  = auto()

class Faction(Enum):
    CORP     = "기업 네트워크"
    CITIZENS = "시민 연합"
    GHOSTS   = "고스트 갱"

class CombatAction(Enum):
    ATTACK  = "공격"
    SKILL   = "스킬"
    ITEM    = "아이템"
    FLEE    = "도주"


ZONE_NAMES = {
    Zone.NEON_COMMERCIAL: "네온 상업지구",
    Zone.RESIDENTIAL:     "주거 블록",
    Zone.LOW_SIGNAL:      "저신호 빈민구역",
    Zone.INDUSTRIAL:      "산업 폐쇄구역",
    Zone.ROOFTOP_NETWORK: "옥상 네트워크",
}

ZONE_COLORS = {
    Zone.NEON_COMMERCIAL: "magenta",
    Zone.RESIDENTIAL:     "cyan",
    Zone.LOW_SIGNAL:      "green",
    Zone.INDUSTRIAL:      "yellow",
    Zone.ROOFTOP_NETWORK: "blue",
}

ZONE_PROPS = {
    Zone.NEON_COMMERCIAL:  dict(light=0.9, surv=0.8, err=0.02, npc=0.15, danger=0.2),
    Zone.RESIDENTIAL:      dict(light=0.6, surv=0.4, err=0.05, npc=0.10, danger=0.3),
    Zone.LOW_SIGNAL:       dict(light=0.3, surv=0.1, err=0.15, npc=0.08, danger=0.6),
    Zone.INDUSTRIAL:       dict(light=0.2, surv=0.5, err=0.20, npc=0.03, danger=0.5),
    Zone.ROOFTOP_NETWORK:  dict(light=0.7, surv=0.3, err=0.08, npc=0.05, danger=0.4),
}

JOBS = [
    ("배달 기사",   "이동속도+, 상업/주거 이벤트+, 초기 자전거 보유"),
    ("편의점 직원", "심야 안정+, 저신호 NPC 친밀+, 초기 식량 보유"),
    ("서버 보조",   "데이터 저항+, 산업/옥상 이벤트+, 신호 스니퍼 보유"),
    ("택시 기사",   "전구역 소문+, 감시 회피+, 초기 크레딧 2배"),
    ("무직",        "전 구역 자유 접근, 초기 스탯 균형, 특수 이벤트+"),
]


# ═══════════════════════════════════════════
#  § 3. 아이템 시스템
# ═══════════════════════════════════════════
@dataclass
class Item:
    id: str
    name: str
    desc: str
    grade: ItemGrade = ItemGrade.COMMON
    weight: float = 0.5
    stackable: bool = False
    qty: int = 1
    equippable: bool = False
    slot: str = ""          # "weapon" / "armor" / "accessory"
    # 효과
    hp_restore: int = 0
    stress_reduce: int = 0
    hunger_restore: int = 0
    fov_bonus: int = 0      # 턴 기반
    stealth_bonus: int = 0
    attack_bonus: int = 0
    defense_bonus: int = 0
    duration: int = 0       # 지속 턴
    price: int = 10

ITEM_DB: Dict[str, Item] = {
    "neon_flash":   Item("neon_flash",   "네온 플래시",     "시야 3턴 확장",          grade=ItemGrade.COMMON,    fov_bonus=4,      duration=3,  price=30),
    "fake_id":      Item("fake_id",      "위조 신분증",     "감시 이벤트 1회 회피",   grade=ItemGrade.RARE,      stealth_bonus=20, duration=1,  price=80),
    "battery":      Item("battery",      "임시 배터리팩",   "전자기기 1회 작동",      grade=ItemGrade.COMMON,    price=40),
    "sniffer":      Item("sniffer",      "신호 스니퍼",     "숨겨진 데이터 흐름 표시",grade=ItemGrade.RARE,      price=120, equippable=True, slot="accessory"),
    "memory_chip":  Item("memory_chip",  "기억 조각",       "특정 구역을 변화시킨다", grade=ItemGrade.LEGENDARY, price=500),
    "knife":        Item("knife",        "접이식 나이프",   "공격력+5, 내구도 있음",  grade=ItemGrade.COMMON,    attack_bonus=5,  equippable=True, slot="weapon", price=60),
    "stim_pack":    Item("stim_pack",    "스팀팩",          "HP 30 회복",             grade=ItemGrade.COMMON,    hp_restore=30,   stackable=True,  price=50),
    "ration":       Item("ration",       "압축 식량",       "배고픔 40 회복",         grade=ItemGrade.COMMON,    hunger_restore=40, stackable=True, price=20),
    "coffee":       Item("coffee",       "합성 커피",       "피로 감소, 스트레스+5",  grade=ItemGrade.COMMON,    stress_reduce=-5,  stackable=True, price=15),
    "armor_vest":   Item("armor_vest",   "방탄 조끼",       "방어력+8",               grade=ItemGrade.RARE,      defense_bonus=8,  equippable=True, slot="armor",  price=150),
    "data_chip":    Item("data_chip",    "데이터 칩",       "퀘스트 아이템",          grade=ItemGrade.RARE,      price=200),
    "credits_50":   Item("credits_50",   "크레딧 카드",     "50 크레딧",              grade=ItemGrade.COMMON,    price=50),
}


@dataclass
class Inventory:
    slots: int = 8
    items: List[Optional[Item]] = field(default_factory=lambda: [None]*8)
    equipped: Dict[str, Optional[Item]] = field(default_factory=lambda: {
        "weapon": None, "armor": None, "accessory": None
    })
    max_weight: float = 20.0

    def total_weight(self) -> float:
        return sum(it.weight * it.qty for it in self.items if it)

    def add(self, item: Item) -> bool:
        if self.total_weight() + item.weight > self.max_weight:
            return False
        if item.stackable:
            for it in self.items:
                if it and it.id == item.id:
                    it.qty += item.qty
                    return True
        for i, slot in enumerate(self.items):
            if slot is None:
                self.items[i] = deepcopy(item)
                return True
        return False

    def remove(self, idx: int):
        if 0 <= idx < len(self.items):
            self.items[idx] = None

    def equip(self, idx: int) -> str:
        item = self.items[idx]
        if not item or not item.equippable:
            return "장착 불가"
        old = self.equipped.get(item.slot)
        self.equipped[item.slot] = item
        self.items[idx] = old
        return f"{item.name} 장착 완료"

    def get_stat(self, attr: str) -> int:
        total = 0
        for it in self.equipped.values():
            if it:
                total += getattr(it, attr, 0)
        return total


# ═══════════════════════════════════════════
#  § 4. 스킬 / 성장 시스템
# ═══════════════════════════════════════════
@dataclass
class Skill:
    name: str
    level: int = 1
    xp: int = 0
    xp_next: int = 100

    def gain_xp(self, amount: int) -> bool:
        """레벨업 시 True"""
        self.xp += amount
        if self.xp >= self.xp_next:
            self.xp -= self.xp_next
            self.level += 1
            self.xp_next = int(self.xp_next * 1.5)
            return True
        return False

    def bar(self, width=8) -> str:
        filled = int(self.xp / self.xp_next * width)
        return '▪' * filled + '·' * (width - filled)


@dataclass
class Stats:
    max_hp: int = 100
    hp: int = 100
    max_stress: int = 100
    stress: int = 20
    stamina: int = 100
    max_stamina: int = 100
    hunger: int = 100        # 100=포만 0=굶주림
    sleep: int = 100         # 100=충분 0=수면부족
    level: int = 1
    xp: int = 0
    xp_next: int = 100
    attack: int = 10
    defense: int = 5
    speed: int = 5
    credits: int = 200

    skills: Dict[str, Skill] = field(default_factory=lambda: {
        "endurance":    Skill("체력"),
        "stealth":      Skill("은신"),
        "negotiation":  Skill("협상"),
        "data_resist":  Skill("데이터저항"),
        "combat":       Skill("전투"),
        "scavenging":   Skill("채집"),
    })

    status: StatusEffect = StatusEffect.NONE
    status_timer: int = 0

    def clamp(self):
        self.hp       = max(0, min(self.max_hp,      self.hp))
        self.stress   = max(0, min(self.max_stress,  self.stress))
        self.stamina  = max(0, min(self.max_stamina, self.stamina))
        self.hunger   = max(0, min(100,              self.hunger))
        self.sleep    = max(0, min(100,              self.sleep))

    def is_alive(self) -> bool:
        return self.hp > 0

    def gain_xp(self, amount: int) -> bool:
        self.xp += amount
        if self.xp >= self.xp_next:
            self.xp -= self.xp_next
            self.level += 1
            self.xp_next = int(self.xp_next * 1.6)
            self.max_hp += 5
            self.hp = min(self.hp + 5, self.max_hp)
            self.attack += 1
            return True
        return False

    def skill_xp(self, skill: str, amount: int = 10) -> bool:
        if skill in self.skills:
            return self.skills[skill].gain_xp(amount)
        return False

    def total_attack(self, inv: "Inventory") -> int:
        return self.attack + inv.get_stat("attack_bonus")

    def total_defense(self, inv: "Inventory") -> int:
        return self.defense + inv.get_stat("defense_bonus")


# ═══════════════════════════════════════════
#  § 5. 평판 & 파벌 & 범죄 시스템
# ═══════════════════════════════════════════
@dataclass
class ReputationSystem:
    faction_rep: Dict[str, int] = field(default_factory=lambda: {
        "CORP": 0, "CITIZENS": 0, "GHOSTS": 0
    })
    wanted_level: int = 0          # 0~5
    crime_timer: float = 0.0       # 자연 감소 타이머
    total_crimes: int = 0

    def modify(self, faction: str, delta: int):
        if faction in self.faction_rep:
            self.faction_rep[faction] = max(-100, min(100, self.faction_rep[faction] + delta))

    def add_crime(self, severity: int = 1):
        self.wanted_level = min(5, self.wanted_level + severity)
        self.total_crimes += severity

    def tick(self, dt: float):
        if self.wanted_level > 0:
            self.crime_timer += dt
            if self.crime_timer > 60.0 / self.wanted_level:
                self.wanted_level = max(0, self.wanted_level - 1)
                self.crime_timer = 0

    def dominant_faction(self) -> Optional[str]:
        max_rep = max(self.faction_rep.values())
        if max_rep <= 0:
            return None
        for k, v in self.faction_rep.items():
            if v == max_rep:
                return k
        return None

    def wanted_label(self) -> str:
        labels = ["없음", "주의", "수배", "위험", "긴급", "최고위험"]
        return labels[self.wanted_level]


# ═══════════════════════════════════════════
#  § 6. 퀘스트 시스템
# ═══════════════════════════════════════════
@dataclass
class Quest:
    id: str
    title: str
    desc: str
    objectives: List[str]
    completed_obj: List[bool] = field(default_factory=list)
    reward_credits: int = 100
    reward_xp: int = 50
    reward_item: Optional[str] = None
    completed: bool = False
    failed: bool = False
    giver: str = ""

    def __post_init__(self):
        if not self.completed_obj:
            self.completed_obj = [False] * len(self.objectives)

    def complete_objective(self, idx: int) -> bool:
        if 0 <= idx < len(self.objectives):
            self.completed_obj[idx] = True
        if all(self.completed_obj):
            self.completed = True
            return True
        return False

    def progress_str(self) -> str:
        done = sum(self.completed_obj)
        return f"{done}/{len(self.objectives)}"


QUEST_POOL: List[Quest] = [
    Quest("find_person", "실종된 시민",
          "누군가 연락이 끊긴 시민을 찾고 있다.",
          ["저신호 구역 탐색", "단서 수집 (NPC 대화 3회)", "위치 확인"],
          reward_credits=150, reward_xp=80, reward_item="stim_pack", giver="익명"),
    Quest("deliver_chip", "데이터 칩 전달",
          "이 칩을 산업 구역 서버실에 꽂아라.",
          ["데이터 칩 수령", "산업 구역 도달", "서버 터미널 사용"],
          reward_credits=200, reward_xp=100, reward_item="fake_id", giver="고스트"),
    Quest("fix_errors", "오류 진정",
          "저신호 구역의 오류 확산을 막아라.",
          ["오류 지점 3곳 방문", "신호 스니퍼 사용"],
          reward_credits=120, reward_xp=60, giver="시민"),
    Quest("intel_gather", "정보 수집",
          "기업 네트워크의 감시 패턴을 파악하라.",
          ["CCTV 2대 조작", "옥상 구역 도달", "기업 NPC 대화"],
          reward_credits=300, reward_xp=150, reward_item="sniffer", giver="고스트"),
]


# ═══════════════════════════════════════════
#  § 7. 적 시스템
# ═══════════════════════════════════════════
@dataclass
class Enemy:
    id: str
    name: str
    char: str
    x: int; y: int
    hp: int; max_hp: int
    attack: int; defense: int; speed: int
    xp_reward: int
    credit_reward: int
    drop_items: List[str] = field(default_factory=list)
    faction: str = "NONE"
    alert: bool = False
    alert_timer: float = 0.0
    aggro: bool = False

    def is_alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, dmg: int) -> int:
        actual = max(1, dmg - self.defense)
        self.hp = max(0, self.hp - actual)
        return actual


def make_enemy(etype: str, x: int, y: int) -> Enemy:
    templates = {
        "drone": Enemy("drone", "감시 드론",    T_ENEMY_D, x, y, 40, 40,  8,  3, 4, 30, 20, ["battery"],     "CORP"),
        "gang":  Enemy("gang",  "거리 폭력배",  T_ENEMY_G, x, y, 60, 60, 12,  5, 3, 40, 35, ["credits_50"],  "GHOSTS"),
        "error": Enemy("error", "오류 개체",    T_ENEMY_E, x, y, 30, 30,  6,  0, 5, 20, 10, ["data_chip"],   "NONE"),
    }
    return deepcopy(templates.get(etype, templates["gang"]))


# ═══════════════════════════════════════════
#  § 8. NPC 시스템
# ═══════════════════════════════════════════
NPC_LINES = {
    "stranger": ["...", "비가 또.", "여기 자주 와?", "조용히 해.", "∆가 가까워."],
    "merchant": ["뭐 필요해?", "오늘 재고 좀 있어.", "돈 없으면 꺼져."],
    "quest":    ["부탁이 있어.", "시간 있어?", "위험한 일이야."],
    "faction":  ["우리 편이야?", "배신은 없어.", "도시를 바꾸자."],
}

@dataclass
class NPC:
    x: int; y: int
    name: str = "시민"
    char: str = T_NPC
    role: str = "stranger"     # stranger / merchant / quest / faction
    zone: Zone = Zone.RESIDENTIAL
    memory: int = 0
    mood: float = 0.5
    faction: Optional[str] = None
    quest_id: Optional[str] = None
    shop_inv: List[str] = field(default_factory=list)

    def get_line(self) -> str:
        pool = NPC_LINES.get(self.role, NPC_LINES["stranger"])
        if self.memory > 5:
            return random.choice(["또 왔네.", "낯이 익어.", "살아있구나."])
        return random.choice(pool)


# ═══════════════════════════════════════════
#  § 9. 맵 타일
# ═══════════════════════════════════════════
@dataclass
class Tile:
    char: str = T_FLOOR
    zone: Zone = Zone.RESIDENTIAL
    walkable: bool = True
    is_neon: bool = False
    visit_count: int = 0
    error_level: float = 0.0
    interactive: str = ""    # "door" / "terminal" / "cctv" / "chest"
    item_drop: Optional[str] = None   # 아이템 ID


# ═══════════════════════════════════════════
#  § 10. 플레이어
# ═══════════════════════════════════════════
@dataclass
class Player:
    x: int = MAP_W // 2
    y: int = MAP_H // 2
    job: str = "무직"
    job_desc: str = ""
    stats: Stats = field(default_factory=Stats)
    inventory: Inventory = field(default_factory=Inventory)
    reputation: ReputationSystem = field(default_factory=ReputationSystem)

    # 감정 수치
    fatigue: float = 20.0
    isolation: float = 30.0
    stability: float = 60.0
    anxiety: float = 20.0

    # 엔딩 누적
    sync_score: int = 0
    decay_score: int = 0
    network_score: int = 0

    # 임시 버프
    fov_bonus_turns: int = 0
    stealth_active: int = 0

    visited_zones: Dict = field(default_factory=dict)
    npc_contacts: int = 0

    active_quests: List[Quest] = field(default_factory=list)
    completed_quests: List[str] = field(default_factory=list)

    def is_distorted(self) -> bool:
        return self.anxiety > 80 or self.isolation > 85 or self.stats.stress > 85

    def fov_radius(self, weather: Weather) -> int:
        r = BASE_FOV
        r += self.fov_bonus_turns > 0 and 4 or 0
        if weather == Weather.HEAVY: r -= 3
        elif weather == Weather.RAIN: r -= 1
        if self.is_distorted(): r -= 2
        sk_level = self.stats.skills.get("endurance", Skill("")).level
        r += sk_level // 3
        return max(3, r)

    def clamp_emotions(self):
        self.fatigue   = max(0.0, min(100.0, self.fatigue))
        self.isolation = max(0.0, min(100.0, self.isolation))
        self.stability = max(0.0, min(100.0, self.stability))
        self.anxiety   = max(0.0, min(100.0, self.anxiety))


# ═══════════════════════════════════════════
#  § 11. 맵 생성
# ═══════════════════════════════════════════
def _zone_at(x, y) -> Zone:
    cx, cy = x / MAP_W, y / MAP_H
    dc = math.hypot(cx - 0.5, cy - 0.5)
    if dc < 0.15:                        return Zone.LOW_SIGNAL
    if cx < 0.5 and cy < 0.5:           return Zone.NEON_COMMERCIAL
    if cx >= 0.5 and cy < 0.5:          return Zone.ROOFTOP_NETWORK
    if cx < 0.5 and cy >= 0.5:          return Zone.RESIDENTIAL
    return Zone.INDUSTRIAL

def generate_map() -> List[List[Tile]]:
    tiles = [[Tile() for _ in range(MAP_W)] for _ in range(MAP_H)]
    for y in range(MAP_H):
        for x in range(MAP_W):
            z = _zone_at(x, y)
            t = tiles[y][x]
            t.zone = z
            r = random.random()
            if r < 0.10:   t.char = T_BUILD;  t.walkable = False
            elif r < 0.14: t.char = T_WALL;   t.walkable = False
            elif r < 0.18: t.char = T_ROAD;   t.walkable = True
            elif r < 0.20 and z == Zone.NEON_COMMERCIAL:
                t.char = T_NEON; t.is_neon = True
            elif r < 0.22 and z in (Zone.INDUSTRIAL, Zone.LOW_SIGNAL):
                t.char = T_ERROR; t.error_level = random.uniform(0.3, 0.8)
            else:
                t.char = T_FLOOR

            if z == Zone.NEON_COMMERCIAL and random.random() < 0.04 and t.walkable:
                t.is_neon = True; t.char = T_NEON

    # 상호작용 오브젝트 배치
    for _ in range(20):
        x, y = random.randint(0, MAP_W-1), random.randint(0, MAP_H-1)
        if tiles[y][x].walkable:
            tiles[y][x].interactive = "terminal"
            tiles[y][x].char = T_TERM
    for _ in range(15):
        x, y = random.randint(0, MAP_W-1), random.randint(0, MAP_H-1)
        if not tiles[y][x].walkable:
            tiles[y][x].interactive = "door"
            tiles[y][x].char = T_DOOR
            tiles[y][x].walkable = False
    for _ in range(12):
        x, y = random.randint(0, MAP_W-1), random.randint(0, MAP_H-1)
        if tiles[y][x].walkable:
            tiles[y][x].interactive = "cctv"
            tiles[y][x].char = T_CCTV
    for _ in range(25):
        x, y = random.randint(0, MAP_W-1), random.randint(0, MAP_H-1)
        if tiles[y][x].walkable:
            tiles[y][x].item_drop = random.choice(list(ITEM_DB.keys()))
            tiles[y][x].char = T_ITEM

    # 플레이어 시작점 클리어
    cx, cy = MAP_W // 2, MAP_H // 2
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            nx, ny = cx+dx, cy+dy
            if 0 <= nx < MAP_W and 0 <= ny < MAP_H:
                t = tiles[ny][nx]
                t.char = T_FLOOR; t.walkable = True
                t.interactive = ""; t.item_drop = None
    return tiles

def generate_npcs(tiles) -> List[NPC]:
    npcs = []
    roles = ["stranger"]*60 + ["merchant"]*15 + ["quest"]*10 + ["faction"]*15
    random.shuffle(roles)
    att = 0
    for role in roles:
        placed = False
        while not placed and att < 10000:
            att += 1
            x = random.randint(1, MAP_W-2)
            y = random.randint(1, MAP_H-2)
            if tiles[y][x].walkable:
                z = tiles[y][x].zone
                npc = NPC(x=x, y=y, role=role, zone=z)
                if role == "merchant":
                    npc.char = T_MERCH
                    npc.name = "상인"
                    npc.shop_inv = random.sample(list(ITEM_DB.keys()), min(4, len(ITEM_DB)))
                elif role == "quest":
                    npc.name = "의뢰인"
                    available = [q for q in QUEST_POOL]
                    if available:
                        npc.quest_id = random.choice(available).id
                elif role == "faction":
                    npc.faction = random.choice(["CORP", "CITIZENS", "GHOSTS"])
                    npc.name = {"CORP":"기업원","CITIZENS":"시민군","GHOSTS":"고스트"}[npc.faction]
                npcs.append(npc)
                placed = True
    return npcs

def generate_enemies(tiles) -> List[Enemy]:
    enemies = []
    types_by_zone = {
        Zone.NEON_COMMERCIAL:  ["drone"],
        Zone.RESIDENTIAL:      ["gang", "drone"],
        Zone.LOW_SIGNAL:       ["gang", "error"],
        Zone.INDUSTRIAL:       ["drone", "error"],
        Zone.ROOFTOP_NETWORK:  ["drone", "gang"],
    }
    cx, cy = MAP_W // 2, MAP_H // 2
    for _ in range(60):
        x = random.randint(1, MAP_W-2)
        y = random.randint(1, MAP_H-2)
        if abs(x - cx) < 15 and abs(y - cy) < 15:
            continue   # 스타트 지점 15칸 이내 스폰 금지
        if tiles[y][x].walkable:
            z = _zone_at(x, y)
            etype = random.choice(types_by_zone.get(z, ["gang"]))
            enemies.append(make_enemy(etype, x, y))
    return enemies


# ═══════════════════════════════════════════
#  § 12. 전투 시스템
# ═══════════════════════════════════════════
@dataclass
class CombatState:
    active: bool = False
    enemy: Optional[Enemy] = None
    log: List[str] = field(default_factory=list)
    turn: int = 0           # 0=플레이어, 1=적
    cursor: int = 0         # 행동 선택 커서
    result: str = ""        # "win" / "lose" / "flee"
    flee_chance: int = 40

    def push_log(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 8:
            self.log.pop(0)

def player_attack(cs: CombatState, player: Player) -> str:
    base = player.stats.total_attack(player.inventory)
    variance = random.randint(-3, 3)
    dmg = max(1, base + variance)
    # 전투 스킬 보너스
    combat_level = player.stats.skills["combat"].level
    dmg += combat_level // 2
    actual = cs.enemy.take_damage(dmg)
    player.stats.skill_xp("combat", 8)
    return f"공격! {actual} 피해"

def player_skill_use(cs: CombatState, player: Player) -> str:
    level = player.stats.skills["combat"].level
    if level >= 3:
        dmg = player.stats.total_attack(player.inventory) * 2
        actual = cs.enemy.take_damage(dmg)
        return f"강타! {actual} 대미지"
    elif level >= 2:
        player.stats.stress = max(0, player.stats.stress - 20)
        return "집중. 스트레스 -20"
    else:
        return "스킬 부족 (전투Lv2 필요)"

def enemy_attack(cs: CombatState, player: Player) -> str:
    if not cs.enemy:
        return ""
    base = cs.enemy.attack
    dmg = max(1, base + random.randint(-2, 2) - player.stats.total_defense(player.inventory))
    player.stats.hp = max(0, player.stats.hp - dmg)
    player.stats.stress = min(100, player.stats.stress + 10)
    player.stats.clamp()
    return f"{cs.enemy.name} 공격! {dmg} 피해"


# ═══════════════════════════════════════════
#  § 13. 게임 이벤트
# ═══════════════════════════════════════════
EVENTS_BY_ZONE = {
    Zone.NEON_COMMERCIAL: [
        "전광판에 당신 얼굴이 스쳤다.", "광고 드론이 스캔했다.",
        "신분 확인 요청.", "네온이 깜빡였다.", "화면이 잠깐 꺼졌다.",
    ],
    Zone.RESIDENTIAL: [
        "아이가 창문으로 내려다봤다.", "냄새. 오래된 음식.",
        "이웃이 문을 잠갔다.", "라디오 잡음.", "복도가 어두워졌다.",
    ],
    Zone.LOW_SIGNAL: [
        "데이터 손실 감지.", "신호 없음.", "누군가 따라오는 느낌.",
        "벽에 지워진 낙서.", "전등이 깜빡였다.",
    ],
    Zone.INDUSTRIAL: [
        "기계음이 멈췄다.", "감시 카메라가 향했다.",
        "철문이 잠겨 있다.", "연기. 출처 불명.", "오래된 서버 냄새.",
    ],
    Zone.ROOFTOP_NETWORK: [
        "도시 전체가 보인다.", "무선 신호 감지.",
        "안테나가 당신 방향으로.", "바람. 비. 네온.", "누군가 여기 있었다.",
    ],
}

@dataclass
class EventLog:
    messages: deque = field(default_factory=lambda: deque(maxlen=7))
    active: Optional[str] = None
    active_timer: float = 0.0

    def push(self, msg: str):
        self.messages.appendleft(msg)
        self.active = msg
        self.active_timer = time.time()

    def tick(self):
        if self.active and time.time() - self.active_timer > 3.5:
            self.active = None


# ═══════════════════════════════════════════
#  § 14. 게임 상태 통합
# ═══════════════════════════════════════════
class GameState:
    def __init__(self):
        self.tiles   = generate_map()
        self.player  = Player()
        self.npcs    = generate_npcs(self.tiles)
        self.enemies = generate_enemies(self.tiles)

        self.weather     = Weather.RAIN
        self.time_of_day = 0.3       # 0.0~1.0
        self._start      = time.time()

        self.event_log = EventLog()
        self.combat    = CombatState()

        self.running   = True
        self.ui_mode   = "world"   # world / inventory / quest / character / combat / shop

        self.watcher_pos: Optional[Tuple[int,int]] = None
        self._wtimer    = 0.0
        self._tick_acc  = 0.0
        self._notify    = ""       # 레벨업 등 알림

    # ── 타일 ──
    def tile(self, x, y) -> Optional[Tile]:
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return self.tiles[y][x]
        return None

    # ── 이동 ──
    def move_player(self, dx: int, dy: int):
        if self.combat.active or self.ui_mode != "world":
            return
        p = self.player
        nx, ny = p.x + dx, p.y + dy
        t = self.tile(nx, ny)

        if t and t.interactive == "door":
            self.event_log.push("문이 잠겨 있다. (배터리팩 필요)")
            return

        if t and t.walkable:
            p.x, p.y = nx, ny
            t.visit_count += 1
            p.visited_zones[t.zone] = p.visited_zones.get(t.zone, 0) + 1

            # 아이템 드롭 줍기
            if t.item_drop:
                item = ITEM_DB.get(t.item_drop)
                if item and p.inventory.add(item):
                    self.event_log.push(f"획득: {item.name}")
                    t.item_drop = None; t.char = T_FLOOR
                    p.stats.skill_xp("scavenging", 5)

            self._update_emotions(t)
            self._try_event(t)
            self._try_enemy_encounter()

            # 버프 타이머
            if p.fov_bonus_turns > 0: p.fov_bonus_turns -= 1
            if p.stealth_active > 0:  p.stealth_active -= 1

            # 생존 소모
            p.stats.hunger = max(0, p.stats.hunger - 0.3)
            p.stats.sleep  = max(0, p.stats.sleep  - 0.15)
            p.stats.stamina = max(0, p.stats.stamina - 1)
            p.stats.clamp()

            # 스킬 경험
            p.stats.skill_xp("endurance", 1)

            # 퀘스트 진행 체크
            self._check_quest_progress()

    def _update_emotions(self, t: Tile):
        p = self.player
        props = ZONE_PROPS[t.zone]
        if props['light'] < 0.4:
            p.anxiety += 0.4; p.isolation += 0.2
        else:
            p.anxiety -= 0.1; p.stability += 0.05
        if props['surv'] > 0.6 and p.stealth_active == 0:
            p.anxiety += 0.5
        if t.is_neon:
            p.isolation -= 0.4; p.stability += 0.1
        if t.error_level > 0.5:
            p.anxiety += 0.6
        if self.weather == Weather.HEAVY:
            p.fatigue += 0.4; p.isolation += 0.2
        elif self.weather == Weather.RAIN:
            p.fatigue += 0.1
        p.fatigue += 0.05
        p.clamp_emotions()

    def _try_event(self, t: Tile):
        props = ZONE_PROPS[t.zone]
        chance = 0.04 + props['err'] * 0.4
        if self.player.job == "배달 기사" and t.zone in (Zone.NEON_COMMERCIAL, Zone.RESIDENTIAL):
            chance += 0.06
        if self.time_of_day > 0.75 or self.time_of_day < 0.1:
            chance += 0.04
        if random.random() < chance:
            pool = EVENTS_BY_ZONE.get(t.zone, [])
            if pool:
                self.event_log.push(random.choice(pool))

    def _try_enemy_encounter(self):
        p = self.player
        t = self.tile(p.x, p.y)
        if not t: return
        props = ZONE_PROPS[t.zone]
        chance = props['danger'] * 0.015
        if p.stealth_active > 0:
            chance *= 0.2
        # 수배 레벨에 따라 증가
        chance += p.reputation.wanted_level * 0.01

        for enemy in self.enemies:
            if enemy.is_alive() and abs(enemy.x - p.x) + abs(enemy.y - p.y) <= 1:
                # 직접 접촉 → 전투 시작
                self._start_combat(enemy)
                return

        if random.random() < chance:
            # 구역 기반 랜덤 조우
            zone_enemies = {
                Zone.NEON_COMMERCIAL: "drone",
                Zone.RESIDENTIAL: "gang",
                Zone.LOW_SIGNAL: "gang",
                Zone.INDUSTRIAL: "error",
                Zone.ROOFTOP_NETWORK: "drone",
            }
            etype = zone_enemies.get(t.zone, "gang")
            enemy = make_enemy(etype, p.x, p.y)
            self.enemies.append(enemy)
            self._start_combat(enemy)

    def _start_combat(self, enemy: Enemy):
        self.combat = CombatState(active=True, enemy=enemy)
        self.combat.push_log(f"⚠ {enemy.name} 등장!")
        self.ui_mode = "combat"

    def resolve_combat_action(self, action: CombatAction, item_idx: int = -1):
        cs = self.combat
        p  = self.player
        if not cs.active or not cs.enemy: return

        if action == CombatAction.ATTACK:
            msg = player_attack(cs, p)
            cs.push_log(f"▶ {msg}")
        elif action == CombatAction.SKILL:
            msg = player_skill_use(cs, p)
            cs.push_log(f"▶ {msg}")
        elif action == CombatAction.ITEM:
            if 0 <= item_idx < len(p.inventory.items):
                item = p.inventory.items[item_idx]
                if item:
                    self._use_item(item, item_idx)
                    cs.push_log(f"▶ {item.name} 사용")
                else:
                    cs.push_log("아이템 없음")
                    return
            else:
                cs.push_log("아이템 없음")
                return
        elif action == CombatAction.FLEE:
            if random.randint(1, 100) <= cs.flee_chance:
                cs.result = "flee"
                cs.push_log("▶ 도주 성공!")
                self._end_combat()
                return
            else:
                cs.push_log("▶ 도주 실패!")

        if not cs.enemy.is_alive():
            cs.result = "win"
            cs.push_log(f"✓ {cs.enemy.name} 처치!")
            self._on_combat_win(cs.enemy)
            return

        # 적 턴
        msg = enemy_attack(cs, p)
        cs.push_log(f"◀ {msg}")

        if not p.stats.is_alive():
            cs.result = "lose"
            cs.push_log("✗ 쓰러졌다...")
            self._on_combat_lose()

    def _on_combat_win(self, enemy: Enemy):
        p = self.player
        p.stats.gain_xp(enemy.xp_reward)
        p.stats.credits += enemy.credit_reward
        for drop_id in enemy.drop_items:
            if random.random() < 0.5:
                item = ITEM_DB.get(drop_id)
                if item:
                    p.inventory.add(deepcopy(item))
                    self.event_log.push(f"드롭: {item.name}")
        # 파벌 평판
        if enemy.faction == "CORP":
            p.reputation.modify("CITIZENS", 3)
            p.reputation.modify("GHOSTS", 2)
            p.reputation.modify("CORP", -5)
        elif enemy.faction == "GHOSTS":
            p.reputation.modify("CORP", 2)
            p.reputation.modify("GHOSTS", -5)
        self.event_log.push(f"+{enemy.xp_reward}XP +{enemy.credit_reward}₵")
        self._end_combat()

    def _on_combat_lose(self):
        p = self.player
        p.stats.hp = p.stats.max_hp // 3
        p.stats.stress = min(100, p.stats.stress + 30)
        p.stats.credits = max(0, p.stats.credits - 50)
        p.x, p.y = MAP_W // 2, MAP_H // 2
        self.event_log.push("병원에서 눈을 떴다. -50₵")
        p.reputation.add_crime(0)
        self._end_combat()

    def _end_combat(self):
        # 처치된 적 제거
        self.enemies = [e for e in self.enemies if e.is_alive()]
        self.combat.active = False   # ← 이게 없으면 move_player가 영구 차단됨
        self.ui_mode = "world"

    def _use_item(self, item: Item, idx: int):
        p = self.player
        if item.hp_restore:
            p.stats.hp = min(p.stats.max_hp, p.stats.hp + item.hp_restore)
        if item.stress_reduce:
            p.stats.stress = max(0, p.stats.stress + item.stress_reduce)
        if item.hunger_restore:
            p.stats.hunger = min(100, p.stats.hunger + item.hunger_restore)
        if item.fov_bonus:
            p.fov_bonus_turns = item.duration
        if item.stealth_bonus:
            p.stealth_active = item.duration
        if item.stackable:
            item.qty -= 1
            if item.qty <= 0:
                p.inventory.items[idx] = None
        else:
            p.inventory.items[idx] = None
        p.stats.clamp()

    # ── NPC 상호작용 ──
    def interact(self):
        if self.ui_mode not in ("world",): return
        p = self.player
        for npc in self.npcs:
            if abs(npc.x - p.x) + abs(npc.y - p.y) <= 1:
                npc.memory += 1
                p.npc_contacts += 1
                p.isolation = max(0, p.isolation - 5)
                p.network_score += 1
                p.stats.skill_xp("negotiation", 8)

                if npc.role == "merchant":
                    self.ui_mode = "shop"
                    self._current_npc = npc
                    return
                elif npc.role == "quest" and npc.quest_id:
                    self._offer_quest(npc)
                elif npc.faction:
                    delta = 5 if npc.mood > 0.5 else -2
                    p.reputation.modify(npc.faction, delta)
                    self.event_log.push(f"[{npc.name}] {npc.get_line()} (평판 변화)")
                else:
                    self.event_log.push(f"[{npc.name}] {npc.get_line()}")

                p.reputation.modify("CITIZENS", 1)
                npc.mood = min(1.0, npc.mood + 0.05)
                p.stats.clamp()
                return

        # 오브젝트 상호작용
        t = self.tile(p.x, p.y)
        if t and t.interactive:
            self._interact_object(t)
            return

        self.event_log.push("주변에 아무도 없다.")

    def _interact_object(self, t: Tile):
        p = self.player
        if t.interactive == "terminal":
            p.stats.skill_xp("data_resist", 10)
            p.sync_score += 1
            self.event_log.push("터미널 접속. 데이터 흐름 감지.")
            # 퀘스트 진행
            for q in p.active_quests:
                if q.id == "deliver_chip" and not q.completed_obj[2]:
                    q.complete_objective(2)
                    self.event_log.push("▶ 퀘스트: 서버 터미널 사용 완료")
        elif t.interactive == "cctv":
            p.stats.skill_xp("stealth", 15)
            p.reputation.modify("CORP", -3)
            p.reputation.modify("CITIZENS", 2)
            self.event_log.push("CCTV 루프 걸었다.")
            t.interactive = ""; t.char = T_FLOOR
            # 퀘스트
            for q in p.active_quests:
                if q.id == "intel_gather":
                    for i, obj in enumerate(q.completed_obj):
                        if not obj and "CCTV" in q.objectives[i]:
                            q.complete_objective(i); break
        elif t.interactive == "door":
            has_battery = any(it and it.id == "battery" for it in p.inventory.items)
            if has_battery:
                t.walkable = True; t.interactive = ""; t.char = T_FLOOR
                self.event_log.push("배터리팩으로 문 개방.")
                for i, it in enumerate(p.inventory.items):
                    if it and it.id == "battery":
                        p.inventory.remove(i); break
            else:
                self.event_log.push("잠긴 문. (배터리팩 필요)")

    def _offer_quest(self, npc: NPC):
        p = self.player
        qid = npc.quest_id
        if qid in p.completed_quests:
            self.event_log.push(f"[{npc.name}] 이미 완료된 의뢰야.")
            return
        if any(q.id == qid for q in p.active_quests):
            self.event_log.push(f"[{npc.name}] 진행 중이야. 계속해.")
            return
        quest = next((q for q in QUEST_POOL if q.id == qid), None)
        if quest:
            new_q = deepcopy(quest)
            new_q.giver = npc.name
            p.active_quests.append(new_q)
            self.event_log.push(f"퀘스트 수락: {new_q.title}")
            # 데이터 칩 퀘스트 → 아이템 지급
            if qid == "deliver_chip":
                p.inventory.add(deepcopy(ITEM_DB["data_chip"]))

    def _check_quest_progress(self):
        p = self.player
        t = self.tile(p.x, p.y)
        if not t: return
        for q in p.active_quests:
            if q.completed: continue
            if q.id == "find_person":
                if t.zone == Zone.LOW_SIGNAL and not q.completed_obj[0]:
                    q.complete_objective(0); self.event_log.push("▶ 퀘스트: 저신호 구역 탐색 완료")
                if p.npc_contacts >= 3 and not q.completed_obj[1]:
                    q.complete_objective(1); self.event_log.push("▶ 퀘스트: 단서 수집 완료")
            if q.id == "fix_errors" and t.error_level > 0.5:
                cnt = sum(1 for obj in q.completed_obj if obj)
                if cnt < 3 and not q.completed_obj[min(cnt, 2)]:
                    q.complete_objective(min(cnt, 2))
                    self.event_log.push(f"▶ 퀘스트: 오류 지점 {cnt+1}/3 확인")
            if q.completed:
                self._complete_quest(q)

    def _complete_quest(self, q: Quest):
        p = self.player
        p.stats.credits += q.reward_credits
        p.stats.gain_xp(q.reward_xp)
        if q.reward_item:
            item = ITEM_DB.get(q.reward_item)
            if item: p.inventory.add(deepcopy(item))
        p.completed_quests.append(q.id)
        p.active_quests.remove(q)
        p.network_score += 3
        self.event_log.push(f"✓ 퀘스트 완료: {q.title} (+{q.reward_credits}₵)")

    # ── 상점 ──
    def buy_item(self, item_id: str) -> str:
        p = self.player
        item = ITEM_DB.get(item_id)
        if not item: return "없음"
        rep_discount = 1.0
        if p.reputation.faction_rep.get("CITIZENS", 0) > 30:
            rep_discount = 0.85
        price = int(item.price * rep_discount)
        if p.stats.credits < price:
            return f"크레딧 부족 ({price}₵)"
        if not p.inventory.add(deepcopy(item)):
            return "인벤토리 가득"
        p.stats.credits -= price
        return f"구매: {item.name} -{price}₵"

    # ── 배경 틱 ──
    def tick(self, dt: float):
        elapsed = time.time() - self._start
        self.time_of_day = (elapsed % DAY_LEN) / DAY_LEN

        if random.random() < 0.0008:
            self.weather = random.choice(list(Weather))
        if random.random() < 0.004:
            self._spread_error()

        self._update_watcher(dt)
        self.event_log.tick()
        self.player.reputation.tick(dt)

        p = self.player
        p.fatigue   = max(0, p.fatigue - 0.008)
        p.isolation = min(100, p.isolation + 0.003)
        if 0.25 < self.time_of_day < 0.6:
            p.stability = min(100, p.stability + 0.005)
        p.clamp_emotions()

        # 수면 부족 패널티
        if p.stats.sleep < 20:
            p.stats.stress = min(100, p.stats.stress + 0.05)
            p.anxiety = min(100, p.anxiety + 0.05)
        # 굶주림 패널티
        if p.stats.hunger < 15:
            p.stats.hp = max(1, p.stats.hp - 0.02)
        # 스태미나 자연 회복
        p.stats.stamina = min(p.stats.max_stamina, p.stats.stamina + 0.3)
        p.stats.clamp()

    def _spread_error(self):
        error_tiles = [
            (x, y) for y in range(MAP_H) for x in range(MAP_W)
            if self.tiles[y][x].error_level > 0.5
        ]
        if not error_tiles: return
        ox, oy = random.choice(error_tiles)
        for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
            nx, ny = ox+dx, oy+dy
            t = self.tile(nx, ny)
            if t and t.walkable and t.error_level < 0.3 and random.random() < 0.25:
                t.error_level += 0.2
                if t.error_level > 0.5:
                    t.char = T_ERROR
                    self.player.decay_score += 1

    def _update_watcher(self, dt: float):
        self._wtimer += dt
        if self._wtimer > random.uniform(20, 50):
            self._wtimer = 0
            angle = random.uniform(0, math.pi * 2)
            dist  = random.uniform(10, 22)
            wx = int(self.player.x + dist * math.cos(angle))
            wy = int(self.player.y + dist * math.sin(angle))
            wx = max(0, min(MAP_W-1, wx))
            wy = max(0, min(MAP_H-1, wy))
            self.watcher_pos = (wx, wy)
        if self.watcher_pos:
            wx, wy = self.watcher_pos
            dx, dy = self.player.x - wx, self.player.y - wy
            dist = math.hypot(dx, dy)
            if dist < 5:
                self.event_log.push("∆가 가까이 있다.")
                self.player.anxiety += 4
                self.player.sync_score += 1
                self.player.clamp_emotions()
            if dist > 3 and random.random() < 0.04:
                mx = (1 if dx > 0 else -1 if dx < 0 else 0)
                my = (1 if dy > 0 else -1 if dy < 0 else 0)
                nwx, nwy = wx + mx, wy + my
                t = self.tile(nwx, nwy)
                if t and t.walkable:
                    self.watcher_pos = (nwx, nwy)

    # ── 저장/불러오기 ──
    def save(self) -> str:
        p = self.player
        data = {
            "pos": [p.x, p.y],
            "job": p.job,
            "credits": p.stats.credits,
            "hp": p.stats.hp,
            "level": p.stats.level,
            "xp": p.stats.xp,
            "hunger": p.stats.hunger,
            "sleep": p.stats.sleep,
            "wanted": p.reputation.wanted_level,
            "emotions": [p.fatigue, p.isolation, p.stability, p.anxiety],
        }
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f)
            return "저장 완료"
        except:
            return "저장 실패"


# ═══════════════════════════════════════════
#  § 15. 렌더러
# ═══════════════════════════════════════════
class Renderer:
    def __init__(self, term: Terminal, gs: GameState):
        self.term = term
        self.gs   = gs
        self._last_mode: str = ""   # 이전 모드 추적 (오버레이 깜빡임 방지)

    def _c(self, color: str) -> str:
        t = self.term
        mapping = {
            "magenta": t.magenta, "cyan": t.cyan, "green": t.green,
            "yellow": t.yellow, "blue": t.blue, "red": t.red,
            "white": t.white, "bold": t.bold, "normal": t.normal,
        }
        return mapping.get(color, "")

    def _fov(self) -> set:
        p = self.gs.player
        r = p.fov_radius(self.gs.weather)
        return {(p.x+dx, p.y+dy) for dy in range(-r, r+1)
                for dx in range(-r, r+1) if dx*dx+dy*dy <= r*r}

    def render(self):
        gs   = self.gs
        mode = gs.ui_mode
        mode_changed = (mode != self._last_mode)
        self._last_mode = mode

        if mode == "combat":
            # 전투는 모드 진입 시 한 번 월드 그리고, 이후엔 전투 패널만 갱신
            if mode_changed:
                self._render_world()
            self._render_combat()
        elif mode == "world":
            # 월드 모드는 매 프레임 전체 갱신 (플레이어 이동/이벤트 반영)
            self._render_world()
        else:
            # inventory / quest / character / shop
            # 모드 진입 시 한 번만 월드 배경을 그리고,
            # 이후는 오버레이 패널만 덮어씌워서 깜빡임 제거
            if mode_changed:
                self._render_world()
            overlay = {
                "inventory": self._render_inventory_overlay,
                "quest":     self._render_quest_overlay,
                "character": self._render_character_overlay,
                "shop":      self._render_shop_overlay,
            }.get(mode)
            if overlay:
                overlay()

    def _render_world(self):
        term = self.term
        gs   = self.gs
        p    = gs.player
        visible  = self._fov()
        npc_map  = {(n.x, n.y): n for n in gs.npcs}
        enemy_map= {(e.x, e.y): e for e in gs.enemies if e.is_alive()}
        cur_tile = gs.tile(p.x, p.y)
        zone     = cur_tile.zone if cur_tile else Zone.RESIDENTIAL

        vx = max(0, min(p.x - VIEW_W // 2, MAP_W - VIEW_W))
        vy = max(0, min(p.y - VIEW_H // 2, MAP_H - VIEW_H))

        out = [term.home]   # term.clear 제거 - 행 단위 덮어쓰기로 깜빡임 방지

        for sy in range(VIEW_H):
            row = term.move_yx(sy, 0)
            for sx in range(VIEW_W):
                wx, wy = vx + sx, vy + sy
                if not (0 <= wx < MAP_W and 0 <= wy < MAP_H):
                    row += ' '; continue

                is_vis    = (wx, wy) in visible
                is_player = (wx == p.x and wy == p.y)
                is_watch  = gs.watcher_pos == (wx, wy)
                npc       = npc_map.get((wx, wy))
                enemy     = enemy_map.get((wx, wy))
                t         = gs.tiles[wy][wx]

                if is_player:
                    row += term.bold + term.white + T_PLAYER + term.normal
                elif is_watch and is_vis:
                    row += term.bold + term.red + T_ENEMY_D + term.normal
                elif enemy and is_vis:
                    row += term.bold + term.red + enemy.char + term.normal
                elif npc and is_vis:
                    col = self._c(ZONE_COLORS.get(npc.zone, "white"))
                    ch = T_MERCH if npc.role == "merchant" else T_NPC
                    row += col + ch + term.normal
                elif not is_vis:
                    if t.visit_count > 0:
                        row += term.color(236) + T_DARK + term.normal
                    else:
                        row += ' '
                else:
                    ch = t.char
                    if p.is_distorted() and t.error_level > 0.3 and random.random() < 0.25:
                        ch = random.choice(['%','!','?','#','&'])
                    if t.visit_count > 15:
                        row += term.color(208) + ch + term.normal
                    elif t.is_neon:
                        row += term.bold + term.magenta + ch + term.normal
                    elif t.error_level > 0.5:
                        row += term.bold + term.red + ch + term.normal
                    elif t.interactive in ("terminal", "cctv", "door", "chest"):
                        row += term.bold + term.yellow + ch + term.normal
                    elif t.item_drop:
                        row += term.bold + term.cyan + ch + term.normal
                    elif t.char in (T_WALL, T_BUILD):
                        row += term.color(240) + ch + term.normal
                    elif t.char == T_ROAD:
                        row += term.color(244) + ch + term.normal
                    else:
                        light = ZONE_PROPS[t.zone]['light']
                        col_n = ZONE_COLORS.get(t.zone, "white")
                        if light < 0.4:
                            row += term.color(238) + ch + term.normal
                        elif light < 0.7:
                            row += term.color(245) + ch + term.normal
                        else:
                            row += self._c(col_n) + ch + term.normal
            out.append(row + term.clear_eol)  # 행 끝 잔상 제거

        # ── 사이드 패널 ──
        def pl(y, txt, color=""):
            s = term.move_yx(y, PANEL_X)
            s += (self._c(color) if color else "") + txt + (term.normal if color else "")
            out.append(s)

        tod = gs.time_of_day
        tl = "새벽" if tod < 0.25 else "낮" if tod < 0.5 else "저녁" if tod < 0.75 else "심야"

        pl(0,  "┌──────────────────────┐")
        pl(1,  "│  NEON DRIFT  v2      │", "bold")
        pl(2,  "├──────────────────────┤")
        pl(3,  f"│ {ZONE_NAMES[zone][:8]:<10}           │")
        pl(4,  f"│ {p.job:<8} Lv{p.stats.level:<3}         │")
        pl(5,  f"│ {tl}  {gs.weather.value:<4}  {p.stats.credits}₵  │")
        pl(6,  "├──────────────────────┤")

        def stat_bar(v, mx, w=10):
            f = int(v / mx * w)
            return '█'*f + '░'*(w-f)

        st = p.stats
        pl(7,  f"│ HP  {stat_bar(st.hp,st.max_hp):<10} {st.hp:>3}  │",
           "green" if st.hp > 50 else "yellow" if st.hp > 25 else "red")
        pl(8,  f"│ ST  {stat_bar(st.stress,100):<10} {st.stress:>3}  │",
           "cyan" if st.stress < 50 else "yellow" if st.stress < 80 else "red")
        pl(9,  f"│ 배고픔 {stat_bar(st.hunger,100):<10}     │",
           "white" if st.hunger > 30 else "yellow")
        pl(10, f"│ 수면   {stat_bar(st.sleep,100):<10}     │",
           "white" if st.sleep > 30 else "yellow")
        pl(11, "├──────────────────────┤")
        pl(12, "│ [감정]               │", "bold")
        pl(13, f"│ 피로   {stat_bar(p.fatigue,100,8):<8}      │")
        pl(14, f"│ 불안   {stat_bar(p.anxiety,100,8):<8}      │",
           "yellow" if p.anxiety > 60 else "")
        pl(15, f"│ 고립   {stat_bar(p.isolation,100,8):<8}      │")
        pl(16, "├──────────────────────┤")

        # 수배 레벨
        wanted_colors = ["","","yellow","yellow","red","red"]
        wl = p.reputation.wanted_level
        pl(17, f"│ 수배  {p.reputation.wanted_label():<6}          │",
           wanted_colors[wl] if wl else "")

        # 파벌
        rep = p.reputation.faction_rep
        pl(18, f"│ 기업{rep['CORP']:>+4} 시민{rep['CITIZENS']:>+4}    │")
        pl(19, f"│ 고스트{rep['GHOSTS']:>+4}               │")
        pl(20, "├──────────────────────┤")
        pl(21, "│ [이벤트]             │", "bold")
        for i, ev in enumerate(list(gs.event_log.messages)[:4]):
            msg = ev[:20] if len(ev) > 20 else ev
            pl(22+i, f"│ {msg:<20} │")
        pl(26, "├──────────────────────┤")
        pl(27, "│WASD이동 E상호작용    │")
        pl(28, "│I인벤 J퀘스트 C캐릭  │")
        pl(29, "│S저장  Q종료          │")
        pl(30, "└──────────────────────┘")

        # 활성 메시지
        if gs.event_log.active:
            out.append(term.move_yx(VIEW_H, 0) + term.bold + term.cyan
                       + f" ▶ {gs.event_log.active:<50}" + term.normal)

        # 왜곡 노이즈
        if p.is_distorted() and random.random() < 0.12:
            ny = random.randint(0, VIEW_H-1)
            nx = random.randint(0, VIEW_W-1)
            out.append(term.move_yx(ny, nx) + term.bold + term.red
                       + random.choice(['%','#','!']) + term.normal)

        # 알림
        if gs._notify:
            out.append(term.move_yx(VIEW_H//2, VIEW_W//2 - 10)
                       + term.bold + term.yellow
                       + f"  ★ {gs._notify} ★  " + term.normal)
            gs._notify = ""

        print(''.join(out), end='', flush=True)

    def _render_combat(self):
        term = self.term
        cs   = self.gs.combat
        p    = self.gs.player
        e    = cs.enemy
        if not e: return

        # 배경(월드)은 render()에서 모드 진입 시 한 번만 그려짐 - 여기서 재호출 불필요

        W, H = 50, 22
        ox = (VIEW_W - W) // 2
        oy = (VIEW_H - H) // 2
        out = []

        def box(y, txt, color=""):
            s = term.move_yx(oy+y, ox)
            s += (self._c(color) if color else "")
            s += txt.ljust(W)
            s += (term.normal if color else "")
            out.append(s)

        box(0,  "╔" + "═"*(W-2) + "╗", "bold")
        box(1,  f"║  ⚔  전투  //  {e.name:<20}   ║", "bold")
        box(2,  "╠" + "═"*(W-2) + "╣")

        def hp_bar(v, mx, w=16):
            f = int(v/mx*w); return '█'*f + '░'*(w-f)

        box(3,  f"║  플레이어  HP: {hp_bar(p.stats.hp, p.stats.max_hp):<16} {p.stats.hp:>3}/{p.stats.max_hp}  ║",
            "green" if p.stats.hp > 50 else "red")
        box(4,  f"║  {e.name:<10}  HP: {hp_bar(e.hp, e.max_hp):<16} {e.hp:>3}/{e.max_hp}  ║",
            "yellow" if e.hp > e.max_hp*0.5 else "red")
        box(5,  "╠" + "═"*(W-2) + "╣")
        box(6,  "║  [전투 로그]                              ║", "bold")
        for i, log in enumerate(cs.log[-6:]):
            box(7+i, f"║  {log[:44]:<44}  ║")
        box(13, "╠" + "═"*(W-2) + "╣")
        box(14, "║  [행동 선택]                              ║", "bold")

        actions = [
            (CombatAction.ATTACK, "A: 공격"),
            (CombatAction.SKILL,  "S: 스킬"),
            (CombatAction.ITEM,   "D: 아이템 사용 (1~8번 슬롯)"),
            (CombatAction.FLEE,   "F: 도주"),
        ]
        for i, (act, label) in enumerate(actions):
            prefix = "▶ " if i == cs.cursor else "  "
            col = "cyan" if i == cs.cursor else ""
            box(15+i, f"║  {prefix}{label:<42}  ║", col)
        box(19, "╠" + "═"*(W-2) + "╣")
        box(20, f"║  ATK:{p.stats.total_attack(p.inventory)}  DEF:{p.stats.total_defense(p.inventory)}  "
                f"스트레스:{p.stats.stress:>3}  ║")
        box(21, "╚" + "═"*(W-2) + "╝")

        print(''.join(out), end='', flush=True)

    def _render_inventory_overlay(self):
        term = self.term
        inv  = self.gs.player.inventory
        out  = []
        W, H = 46, 22
        ox, oy = 2, 2

        def box(y, txt, color=""):
            s = term.move_yx(oy+y, ox)
            s += (self._c(color) if color else "") + txt.ljust(W) + (term.normal if color else "")
            out.append(s)

        box(0, "╔" + "═"*(W-2) + "╗", "bold")
        box(1, "║  인벤토리                               ║", "bold")
        box(2, "╠" + "═"*(W-2) + "╣")
        box(3, f"║  무게: {inv.total_weight():.1f}/{inv.max_weight}                          ║")
        box(4, "╠" + "═"*(W-2) + "╣")
        box(5, "║  [슬롯]                                 ║")
        for i, item in enumerate(inv.items):
            if item:
                grade_col = {"일반":"white","희귀":"cyan","전설":"yellow"}
                col = grade_col.get(item.grade.value[0], "white")
                box(6+i, f"║  [{i+1}] {item.name:<12} ×{item.qty:<2} {item.grade.value[0]:<4}    ║", col)
            else:
                box(6+i, f"║  [{i+1}] ─────────────────────────────  ║")
        box(14, "╠" + "═"*(W-2) + "╣")
        box(15, "║  [장착]                                 ║")
        for i, (slot, item) in enumerate(inv.equipped.items()):
            label = {"weapon":"무기","armor":"방어구","accessory":"액세서리"}[slot]
            val = item.name if item else "없음"
            box(16+i, f"║  {label}: {val:<30}     ║")
        box(19, "╠" + "═"*(W-2) + "╣")
        box(20, "║  E[번호]: 사용/장착   I: 닫기          ║")
        box(21, "╚" + "═"*(W-2) + "╝")
        print(''.join(out), end='', flush=True)

    def _render_quest_overlay(self):
        term = self.term
        p    = self.gs.player
        out  = []
        W, H = 46, 22
        ox, oy = 2, 2

        def box(y, txt, color=""):
            s = term.move_yx(oy+y, ox)
            s += (self._c(color) if color else "") + txt.ljust(W) + (term.normal if color else "")
            out.append(s)

        box(0, "╔" + "═"*(W-2) + "╗", "bold")
        box(1, "║  퀘스트 로그                            ║", "bold")
        box(2, "╠" + "═"*(W-2) + "╣")
        box(3, f"║  진행 중: {len(p.active_quests)}   완료: {len(p.completed_quests)}                 ║")
        box(4, "╠" + "═"*(W-2) + "╣")
        row = 5
        for q in p.active_quests[:4]:
            box(row, f"║  ▶ {q.title:<38}  ║", "cyan"); row+=1
            for i, obj in enumerate(q.objectives):
                done = q.completed_obj[i]
                mark = "✓" if done else "·"
                col = "green" if done else ""
                box(row, f"║    {mark} {obj[:38]:<38}  ║", col); row+=1
            box(row, f"║    보상: {q.reward_credits}₵  {q.reward_xp}XP              ║"); row+=1
            if row > 18: break
        while row < 20:
            box(row, "║" + " "*(W-2) + "║"); row+=1
        box(20, "╠" + "═"*(W-2) + "╣")
        box(21, "║  J: 닫기                                ║")
        # 완료 퀘스트 목록 간단 표시
        if p.completed_quests:
            box(22, "╠" + "═"*(W-2) + "╣") if H > 22 else None
        box(min(22, H-1), "╚" + "═"*(W-2) + "╝")
        print(''.join(out), end='', flush=True)

    def _render_character_overlay(self):
        term = self.term
        p    = self.gs.player
        st   = p.stats
        out  = []
        W = 46
        ox, oy = 2, 2

        def box(y, txt, color=""):
            s = term.move_yx(oy+y, ox)
            s += (self._c(color) if color else "") + txt.ljust(W) + (term.normal if color else "")
            out.append(s)

        box(0, "╔" + "═"*(W-2) + "╗", "bold")
        box(1, "║  캐릭터 정보                            ║", "bold")
        box(2, "╠" + "═"*(W-2) + "╣")
        box(3, f"║  {p.job}  Lv.{st.level}  XP:{st.xp}/{st.xp_next}          ║")
        box(4, f"║  HP:{st.hp}/{st.max_hp}  공격:{st.total_attack(p.inventory)}  방어:{st.total_defense(p.inventory)}    ║")
        box(5, f"║  스태미나:{st.stamina}/{st.max_stamina}  스트레스:{st.stress}         ║")
        box(6, f"║  상태이상: {st.status.name:<30}  ║")
        box(7, "╠" + "═"*(W-2) + "╣")
        box(8, "║  [스킬]                                 ║", "bold")
        for i, (sk_id, sk) in enumerate(st.skills.items()):
            box(9+i, f"║  {sk.name:<8} Lv{sk.level:<2} {sk.bar(12):<12}       ║")
        box(15, "╠" + "═"*(W-2) + "╣")
        box(16, "║  [파벌 평판]                            ║", "bold")
        rep = p.reputation
        box(17, f"║  기업:{rep.faction_rep['CORP']:>+4}  시민:{rep.faction_rep['CITIZENS']:>+4}  고스트:{rep.faction_rep['GHOSTS']:>+4}  ║")
        box(18, f"║  수배 레벨: {rep.wanted_label()}  범죄 횟수:{rep.total_crimes}      ║")
        box(19, f"║  지배 파벌: {rep.dominant_faction() or '없음':<30}  ║")
        box(20, "╠" + "═"*(W-2) + "╣")
        box(21, "║  C: 닫기                                ║")
        box(22, "╚" + "═"*(W-2) + "╝")
        print(''.join(out), end='', flush=True)

    def _render_shop_overlay(self):
        term = self.term
        gs   = self.gs
        npc  = getattr(gs, "_current_npc", None)
        if not npc: return
        out  = []
        W = 46
        ox, oy = 2, 2

        def box(y, txt, color=""):
            s = term.move_yx(oy+y, ox)
            s += (self._c(color) if color else "") + txt.ljust(W) + (term.normal if color else "")
            out.append(s)

        box(0, "╔" + "═"*(W-2) + "╗", "bold")
        box(1, f"║  상점  [{npc.name}]                      ║", "bold")
        box(2, f"║  보유 크레딧: {gs.player.stats.credits}₵                  ║")
        box(3, "╠" + "═"*(W-2) + "╣")
        box(4, "║  [판매 목록]                            ║")
        for i, item_id in enumerate(npc.shop_inv[:8]):
            item = ITEM_DB.get(item_id)
            if item:
                col = {"일반":"white","희귀":"cyan","전설":"yellow"}[item.grade.value[0]]
                box(5+i, f"║  [{i+1}] {item.name:<14} {item.price:>4}₵  {item.desc[:12]:<12}  ║", col)
        box(13, "╠" + "═"*(W-2) + "╣")
        box(14, "║  숫자키: 구매   E/Q: 닫기               ║")
        box(15, "╚" + "═"*(W-2) + "╝")
        print(''.join(out), end='', flush=True)


# ═══════════════════════════════════════════
#  § 16. 입력 처리
# ═══════════════════════════════════════════
def handle_input(key, gs: GameState) -> bool:
    k = str(key)
    kn = key.name if hasattr(key, 'name') else ""

    if gs.ui_mode == "combat":
        return _handle_combat_input(k, kn, gs)
    if gs.ui_mode == "inventory":
        return _handle_inventory_input(k, kn, gs)
    if gs.ui_mode == "shop":
        return _handle_shop_input(k, kn, gs)
    if gs.ui_mode in ("quest", "character"):
        if k in ('j','J','c','C','q','Q','i','I'):
            gs.ui_mode = "world"
        return False

    # ── 월드 모드 ──
    move_map = {
        'w':(0,-1), 'a':(-1,0), 's':(0,1), 'd':(1,0),
        'KEY_UP':(0,-1), 'KEY_DOWN':(0,1),
        'KEY_LEFT':(-1,0), 'KEY_RIGHT':(1,0),
    }
    if k.lower() in move_map:
        gs.move_player(*move_map[k.lower()])
    elif kn in move_map:
        gs.move_player(*move_map[kn])
    elif k.lower() == 'e':
        gs.interact()
    elif k.lower() == 'i':
        gs.ui_mode = "inventory"
    elif k.lower() == 'j':
        gs.ui_mode = "quest"
    elif k.lower() == 'c':
        gs.ui_mode = "character"
    elif k.lower() == 's':
        msg = gs.save()
        gs.event_log.push(msg)
    elif k.lower() == 'q':
        return True
    return False

def _handle_combat_input(k, kn, gs: GameState) -> bool:
    cs = gs.combat
    if k == 'a' or kn == 'KEY_UP':
        cs.cursor = max(0, cs.cursor - 1)
    elif k == 'd' or kn == 'KEY_DOWN':
        cs.cursor = min(3, cs.cursor + 1)
    elif k in ('\n', '\r', ' ', 'e') or kn == 'KEY_ENTER':
        actions = [CombatAction.ATTACK, CombatAction.SKILL, CombatAction.ITEM, CombatAction.FLEE]
        action = actions[cs.cursor]
        if action == CombatAction.ITEM:
            # 첫 번째 소비 아이템 자동 사용
            for i, it in enumerate(gs.player.inventory.items):
                if it and it.hp_restore > 0:
                    gs.resolve_combat_action(action, i)
                    return False
            cs.push_log("사용할 아이템 없음")
        else:
            gs.resolve_combat_action(action)
    elif k.lower() == 'q':
        return True
    return False

def _handle_inventory_input(k, kn, gs: GameState) -> bool:
    if k.lower() == 'i' or k.lower() == 'q':
        gs.ui_mode = "world"; return False
    if k in [str(i) for i in range(1,9)]:
        idx = int(k) - 1
        item = gs.player.inventory.items[idx]
        if item:
            if item.equippable:
                msg = gs.player.inventory.equip(idx)
                gs.event_log.push(msg)
            else:
                gs._use_item(item, idx)
                gs.event_log.push(f"{item.name} 사용")
    return False

def _handle_shop_input(k, kn, gs: GameState) -> bool:
    npc = getattr(gs, "_current_npc", None)
    if not npc:
        gs.ui_mode = "world"; return False
    if k.lower() in ('e', 'q'):
        gs.ui_mode = "world"; return False
    if k in [str(i) for i in range(1, 9)]:
        idx = int(k) - 1
        if idx < len(npc.shop_inv):
            msg = gs.buy_item(npc.shop_inv[idx])
            gs.event_log.push(msg)
    return False


# ═══════════════════════════════════════════
#  § 17. 인트로 화면
# ═══════════════════════════════════════════
def show_intro(term: Terminal, gs: GameState):
    print(term.clear + term.home)
    print(term.bold + term.magenta)
    print("""
  ███╗  ██╗███████╗ ██████╗ ███╗  ██╗    ██████╗ ██████╗ ██╗███████╗████████╗
  ████╗ ██║██╔════╝██╔═══██╗████╗ ██║    ██╔══██╗██╔══██╗██║██╔════╝╚══██╔══╝
  ██╔██╗██║█████╗  ██║   ██║██╔██╗██║    ██║  ██║██████╔╝██║█████╗     ██║
  ██║╚████║██╔══╝  ██║   ██║██║╚████║    ██║  ██║██╔══██╗██║██╔══╝     ██║
  ██║ ╚███║███████╗╚██████╔╝██║ ╚███║    ██████╔╝██║  ██║██║██║        ██║
  ╚═╝  ╚══╝╚══════╝ ╚═════╝ ╚═╝  ╚══╝    ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝        ╚═╝
    """ + term.normal)
    print(term.cyan + "  시민 로그 v2  //  당신은 영웅이 아니다.  //  도시가 당신을 만든다.\n" + term.normal)
    print("  직업을 선택하세요:\n")
    for i, (job, desc) in enumerate(JOBS):
        print(f"  [{i+1}] {term.bold}{job:<10}{term.normal}  {desc}")
    print(f"\n  [Enter] 랜덤 시작")
    print(f"\n  조작: WASD이동  E상호작용  I인벤토리  J퀘스트  C캐릭터  S저장  Q종료")
    print(f"  전투: A/D커서이동  Enter/Space 행동 선택\n")

    with term.cbreak():
        while True:
            key = term.inkey(timeout=60)
            k = str(key)
            if k in ('1','2','3','4','5'):
                job, desc = JOBS[int(k)-1]
                gs.player.job = job
                gs.player.job_desc = desc
                # 직업별 시작 아이템
                job_items = {
                    "배달 기사":   ["ration", "stim_pack"],
                    "편의점 직원": ["ration", "ration", "coffee"],
                    "서버 보조":   ["sniffer", "battery"],
                    "택시 기사":   ["fake_id", "credits_50"],
                    "무직":        ["knife", "stim_pack"],
                }
                gs.player.stats.credits = 400 if job == "택시 기사" else 200
                for iid in job_items.get(job, []):
                    gs.player.inventory.add(deepcopy(ITEM_DB[iid]))
                break
            elif k in ('\n', '\r') or (hasattr(key, 'name') and key.name == 'KEY_ENTER'):
                job, desc = random.choice(JOBS)
                gs.player.job = job
                gs.player.job_desc = desc
                break
            elif not key:
                break


# ═══════════════════════════════════════════
#  § 18. 엔딩
# ═══════════════════════════════════════════
def show_ending(term: Terminal, gs: GameState):
    p = gs.player
    scores = [
        ("도시와 동기화",    p.sync_score),
        ("도시 붕괴 방치",   p.decay_score),
        ("시민 네트워크",    p.network_score),
    ]
    ending = max(scores, key=lambda s: s[1])[0]
    df = gs.player.reputation.dominant_faction()

    print(term.clear + term.home)
    print(term.bold + term.magenta + "\n  ──── 기록 종료 ────\n" + term.normal)
    print(f"  직업:     {p.job}  Lv.{p.stats.level}")
    print(f"  방문 구역: {len(p.visited_zones)}개")
    print(f"  퀘스트 완료: {len(p.completed_quests)}개")
    print(f"  처치 수: {p.stats.skills['combat'].level}레벨 전투")
    print(f"  NPC 접촉: {p.npc_contacts}회")
    print(f"  최종 크레딧: {p.stats.credits}₵")
    print(f"  지배 파벌: {df or '없음'}")
    print(f"\n  결말 방향: {term.bold}{ending}{term.normal}")
    print(term.cyan + "\n  당신은 도시를 지나갔다. 도시는 당신을 기억할 것이다.\n" + term.normal)


# ═══════════════════════════════════════════
#  § 19. 메인 루프
# ═══════════════════════════════════════════
def main():
    term = Terminal()
    gs   = GameState()
    ren  = Renderer(term, gs)
    gs._current_npc = None

    with term.fullscreen(), term.hidden_cursor():
        show_intro(term, gs)
        last_tick = time.time()

        with term.cbreak():
            while gs.running:
                now = time.time()
                dt  = now - last_tick
                last_tick = now

                gs.tick(dt)
                ren.render()

                key = term.inkey(timeout=TICK)
                if key:
                    done = handle_input(key, gs)
                    if done:
                        gs.running = False

        show_ending(term, gs)


if __name__ == "__main__":
    main()
