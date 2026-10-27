"""Grade force-or-save decisions by simulating the money each choice leaves you.

A buy round is a decision when the team can afford a force but not a full buy. For both
choices we play the economy forward a few rounds under CS2's money rules (win reward, loss
bonus, gear that survives), with both teams then doing the standard thing: full buy when they
can, save when they can't, spend everything on the last round of a half or at match point.
Each round's win chance comes from both teams' equipment value (rates.equipment_win_rate), and the choice that wins more rounds
is the right call.

Kill rewards are an average measured from real matches, so this is a model of the economy,
not a replay of it.
"""

from dataclasses import dataclass, replace

import pandas as pd

from cs2_insights.demo import ECO_MAX_PER_PLAYER, REGULATION_ROUNDS
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, equipment_win_rate

WIN_REWARD = 3_250
LOSS_BONUS = [1_400, 1_900, 2_400, 2_900, 3_400]
STARTING_LOSSES = 1  # CS2 starts each half one loss in, so a lost pistol pays $1,900
MAX_MONEY = 16_000
# Measured from stored matches: average kill money per player on top of the round reward,
# and the share of equipment value still carried into the next round.
KILL_MONEY_WON = 330
KILL_MONEY_LOST = 40
KEPT_WON = 0.55
KEPT_LOST = 0.10
# Teams only reliably full-buy from about $4,500 each (money plus carried gear): below that someone is short.
FULL_BUY_AFFORDABLE = 4_500
FULL_BUY_COST = 5_000  # the most a full buy spends per player
LOOKAHEAD = 3  # rounds simulated after the decision
# Differences smaller than this many rounds are too close to call.
CLOSE_CALL = 0.10
MATCH_POINT = REGULATION_ROUNDS // 2

FORCE, SAVE = "force", "save"
GOOD_CALL, CLOSE, SHOULD_SAVE, SHOULD_FORCE = "Good call", "Close call", "Should have saved", "Should have forced"


@dataclass(frozen=True)
class Economy:
    """One team's money going into a round, before buying."""

    money: float
    carried: float  # equipment value kept from last round
    loss_counter: int
    players: int

    def after(self, equip: float, bank: float, won: bool) -> "Economy":
        income = WIN_REWARD + KILL_MONEY_WON if won else LOSS_BONUS[self.loss_counter] + KILL_MONEY_LOST
        counter = max(self.loss_counter - 1, 0) if won else min(self.loss_counter + 1, len(LOSS_BONUS) - 1)
        return replace(
            self,
            money=min(bank + income * self.players, MAX_MONEY * self.players),
            carried=equip * (KEPT_WON if won else KEPT_LOST),
            loss_counter=counter,
        )

    def buy(self, spend_all: bool) -> tuple[float, float]:
        """(equipment, money left) for the standard choice: full buy if affordable, else save."""
        total = self.money + self.carried
        if spend_all or total >= FULL_BUY_AFFORDABLE * self.players:
            equip = max(min(total, FULL_BUY_COST * self.players), self.carried)
            return equip, total - equip
        return self.carried, self.money


def economy_states(team_rounds: pd.DataFrame) -> pd.DataFrame:
    """Per (round, team): money at round start, loss counter, and rounds left in the half."""
    frames = []
    for team, group in team_rounds.groupby("team"):
        group = group.sort_values("round").reset_index(drop=True)
        half = (group["side"] != group["side"].shift()).cumsum()
        counters, counter = [], STARTING_LOSSES
        for i, row in group.iterrows():
            if i and half[i] != half[i - 1]:
                counter = STARTING_LOSSES
            counters.append(counter)
            counter = max(counter - 1, 0) if row["won"] else min(counter + 1, len(LOSS_BONUS) - 1)
        frames.append(
            pd.DataFrame(
                {
                    "round": group["round"],
                    "team": team,
                    "start_money": group["bank"] + group["cash_spent"],
                    "loss_counter": counters,
                    "rounds_left_in_half": group.groupby(half)["round"].transform("max") - group["round"],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _play(slope: float, mine: Economy, theirs: Economy, my_buy: tuple, their_buy: tuple, p: float,
          rounds_left: int, depth: int, scores: tuple[int, int], in_regulation: bool) -> float:
    """Expected rounds won after a round whose buys and win chance are known."""
    total = 0.0
    for won, weight in ((True, p), (False, 1 - p)):
        new_scores = (scores[0] + won, scores[1] + (not won))
        if depth == 0 or rounds_left <= 0 or (in_regulation and MATCH_POINT + 1 in new_scores):
            continue
        total += weight * _round(
            slope, mine.after(*my_buy, won), theirs.after(*their_buy, not won),
            rounds_left - 1, depth - 1, new_scores, in_regulation,
        )
    return total


def _round(slope: float, mine: Economy, theirs: Economy, rounds_left: int, depth: int,
           scores: tuple[int, int], in_regulation: bool) -> float:
    """Expected rounds won from this round on, both teams playing the standard economy."""
    # Money is worthless on the last round of a half, or when losing this round ends the match.
    my_buy = mine.buy(spend_all=rounds_left == 0 or (in_regulation and scores[1] == MATCH_POINT))
    their_buy = theirs.buy(spend_all=rounds_left == 0 or (in_regulation and scores[0] == MATCH_POINT))
    p = equipment_win_rate(my_buy[0] / mine.players, their_buy[0] / theirs.players, slope)
    return p + _play(slope, mine, theirs, my_buy, their_buy, p, rounds_left, depth, scores, in_regulation)


def grade_decisions(team_rounds: pd.DataFrame, team: str, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> pd.DataFrame:
    """One row per force-or-save decision `team` made, with both choices' expected rounds won."""
    states = economy_states(team_rounds).set_index(["round", "team"])
    rounds = team_rounds.set_index(["round", "team"])
    their_team = "B" if team == "A" else "A"
    rows = []
    for number in sorted(team_rounds["round"].unique()):
        mine, theirs = rounds.loc[(number, team)], rounds.loc[(number, their_team)]
        state, their_state = states.loc[(number, team)], states.loc[(number, their_team)]
        n = int(mine["players"])
        resources = state["start_money"] + mine["start_equip_value"]
        if mine["buy_type"] == "pistol" or not ECO_MAX_PER_PLAYER <= resources / n < FULL_BUY_AFFORDABLE:
            continue  # nothing to decide: a pistol round, a forced eco, or an affordable full buy

        # Each choice as (equipment this round, money left). The choice actually made uses the real numbers.
        choices = {SAVE: (mine["start_equip_value"], state["start_money"]), FORCE: (resources, 0)}
        made = FORCE if mine["buy_type"] in ("force", "full") else SAVE
        choices[made] = (mine["equip_value"], mine["bank"])

        mine_now = Economy(state["start_money"], mine["start_equip_value"], int(state["loss_counter"]), n)
        theirs_now = Economy(their_state["start_money"], theirs["start_equip_value"], int(their_state["loss_counter"]), int(theirs["players"]))
        their_buy = (theirs["equip_value"], theirs["bank"])
        scores = (int(mine["score"]), int(mine["opponent_score"]))
        values, now = {}, {}
        for choice, my_buy in choices.items():
            p = now[choice] = equipment_win_rate(my_buy[0] / n, their_buy[0] / int(theirs["players"]), slope)
            values[choice] = p + _play(
                slope, mine_now, theirs_now, my_buy, their_buy, p,
                int(state["rounds_left_in_half"]), LOOKAHEAD, scores, number <= REGULATION_ROUNDS,
            )

        other = SAVE if made == FORCE else FORCE
        gap = values[made] - values[other]
        if abs(gap) < CLOSE_CALL:
            grade = CLOSE
        elif gap > 0:
            grade = GOOD_CALL
        else:
            grade = SHOULD_SAVE if made == FORCE else SHOULD_FORCE
        rows.append(
            {
                "round": int(number),
                "money_each": int(resources / n),
                "their_buy": theirs["buy_type"],
                "made": made,
                "force_now": round(now[FORCE], 2),
                "save_now": round(now[SAVE], 2),
                "force_wins": round(values[FORCE], 2),
                "save_wins": round(values[SAVE], 2),
                "rounds_counted": 1 + min(LOOKAHEAD, int(state["rounds_left_in_half"])),
                "grade": grade,
                "cost": round(max(-gap, 0), 2),
            }
        )
    columns = ["round", "money_each", "their_buy", "made", "force_now", "save_now", "force_wins", "save_wins", "rounds_counted", "grade", "cost"]
    return pd.DataFrame(rows, columns=columns)
