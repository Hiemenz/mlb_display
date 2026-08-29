"""
Additional coverage for src/game_detail_fetch.py.

test_scoreboard_rules.py already covers: _abbr_play, _fielder_from_desc,
_fielder_seq_from_desc (all in image_box), plus a solid slice of
_build_scorecard_notation, _parse_review_context, and _find_recent_review_result
(the "currentPlay has a review" branches). This file focuses on everything else:
select_game, fetch_live_feed, the five fetch_* public functions (mocking
fetch_live_feed), and the private helpers not already exercised.
"""

import copy

import pytest
from unittest.mock import patch, MagicMock

import game_detail_fetch as gdf
from game_detail_fetch import (
    select_game,
    fetch_live_feed,
    fetch_scoreboard_live_extras,
    fetch_between_inning_info,
    fetch_scorecard_data,
    _extract_pitches_detailed,
    _count_abs_challenges_used,
    _count_replay_challenges_used,
    _parse_review_context,
    _find_recent_review_result,
    _last_name_simple,
    _find_recent_sub_event,
    _get_player_info,
    _build_lineup_at_bats,
    _extract_pitchers,
    _build_scorecard_notation,
    _build_current_half_inning_outs,
    _extract_all_hit_coordinates,
    _map_event_to_code,
    _pos_from_desc,
)


# ===========================================================================
# Fixture builder: synthetic live-feed dict
# ===========================================================================

def _deep_merge(base, overrides):
    """Deep merge."""
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _live_feed(**overrides):
    """Return a synthetic live-feed dict shaped like the real MLB API response.
    Pass nested-dict overrides to tweak just what a test needs, e.g.
    _live_feed(liveData={'linescore': {'currentInning': 11}}).
    """
    base = {
        'gameData': {
            'status': {'detailedState': 'In Progress'},
            'teams': {
                'away': {'abbreviation': 'BOS', 'id': 111},
                'home': {'abbreviation': 'NYY', 'id': 147},
            },
            'venue': {'id': 3313, 'name': 'Yankee Stadium'},
            'probablePitchers': {
                'away': {'fullName': 'Reid Ray'},
                'home': {'fullName': 'Logan Webb'},
            },
            'datetime': {'dateTime': '2026-06-20T23:05:00Z'},
        },
        'liveData': {
            'linescore': {
                'currentInning': 5,
                'currentInningOrdinal': '5th',
                'inningState': 'Top',
                'balls': 1,
                'strikes': 2,
                'outs': 1,
                'teams': {
                    'away': {'runs': 2, 'hits': 5, 'errors': 0},
                    'home': {'runs': 1, 'hits': 4, 'errors': 0},
                },
                'innings': [
                    {'num': 1, 'away': {'runs': 0}, 'home': {'runs': 1}},
                    {'num': 2, 'away': {'runs': 1}, 'home': {'runs': 0}},
                ],
                'offense': {
                    'batter': {'id': 1, 'fullName': 'Mookie Betts'},
                    'first': {'id': 2, 'fullName': 'X'},
                    'onDeck': {'id': 3, 'fullName': 'Y'},
                    'inHole': {'id': 4, 'fullName': 'Z'},
                },
                'defense': {'pitcher': {'id': 5, 'fullName': 'Logan Webb'}},
            },
            'plays': {
                'currentPlay': {
                    'matchup': {'batter': {'id': 1, 'fullName': 'Mookie Betts'}, 'pitcher': {'id': 5}},
                    'result': {'event': '', 'eventType': '', 'description': '', 'rbi': 0},
                    'about': {'inning': 5, 'isTopInning': True, 'isComplete': False, 'halfInning': 'top'},
                    'playEvents': [],
                },
                'allPlays': [],
            },
            'boxscore': {
                'teams': {
                    'away': {
                        'players': {
                            'ID1': {
                                'person': {'id': 1, 'fullName': 'Mookie Betts'},
                                'stats': {'batting': {'hits': 1, 'atBats': 3}, 'pitching': {}},
                                'seasonStats': {'batting': {}, 'pitching': {}},
                                'position': {'code': '9', 'abbreviation': 'RF'},
                                'jerseyNumber': '50',
                                'battingOrder': '100',
                            },
                            'ID2': {
                                'person': {'id': 2, 'fullName': 'X'},
                                'stats': {'batting': {}, 'pitching': {}},
                                'seasonStats': {'batting': {}, 'pitching': {}},
                                'position': {'code': '7', 'abbreviation': 'LF'},
                                'jerseyNumber': '21',
                                'battingOrder': '200',
                            },
                        },
                        'pitchers': [5],
                        'battingOrder': [1, 2],
                    },
                    'home': {
                        'players': {
                            'ID5': {
                                'person': {'id': 5, 'fullName': 'Logan Webb'},
                                'stats': {
                                    'pitching': {
                                        'numberOfPitches': 42, 'inningsPitched': '5.0',
                                        'hits': 4, 'earnedRuns': 1, 'strikeOuts': 6,
                                    },
                                    'batting': {},
                                },
                                'seasonStats': {'batting': {}, 'pitching': {}},
                                'position': {'code': '1', 'abbreviation': 'P'},
                                'jerseyNumber': '62',
                                'battingOrder': '900',
                            },
                        },
                        'pitchers': [5],
                        'battingOrder': [5],
                    },
                },
            },
            'decisions': {
                'winner': {'fullName': 'Logan Webb'},
                'loser': {'fullName': 'Reid Ray'},
                'save': {},
            },
        },
    }
    return _deep_merge(copy.deepcopy(base), overrides)


def _play(event='', event_type='', description='', inning=1, is_top=True,
          is_complete=True, half=None, batter_id=1, batter_name='Batter',
          rbi=0, credits=None, play_events=None, hit_data=None):
    """Build a minimal allPlays-style play dict."""
    return {
        'result': {'event': event, 'eventType': event_type, 'description': description, 'rbi': rbi},
        'about': {
            'inning': inning, 'isTopInning': is_top, 'isComplete': is_complete,
            'halfInning': half or ('top' if is_top else 'bottom'),
        },
        'matchup': {'batter': {'id': batter_id, 'fullName': batter_name}},
        'credits': credits or [],
        'playEvents': play_events or [],
        'hitData': hit_data or {},
        'runners': [],
    }


# ===========================================================================
# select_game
# ===========================================================================

class TestSelectGame:
    team_data = {'team_abbreviation': {'111': 'BOS', '147': 'NYY', '133': 'OAK'}}

    def _game(self, **kw):
        """Game."""
        g = {'away_team_id': 111, 'home_team_id': 147, 'detailed_state': 'Scheduled'}
        g.update(kw)
        return g

    def test_empty_games_returns_none(self):
        """Empty games returns none."""
        assert select_game([], 'BOS', self.team_data) is None

    def test_no_favorite_returns_first_live_game(self):
        """No favorite returns first live game."""
        games = [
            self._game(detailed_state='Scheduled'),
            self._game(detailed_state='In Progress', away_team_id=133, home_team_id=999),
        ]
        result = select_game(games, None, self.team_data)
        assert result['detailed_state'] == 'In Progress'

    def test_no_favorite_no_live_returns_first_game(self):
        """No favorite no live returns first game."""
        games = [self._game(detailed_state='Scheduled'), self._game(detailed_state='Final')]
        result = select_game(games, None, self.team_data)
        assert result is games[0]

    def test_favorite_live_preferred_over_scheduled(self):
        """Favorite live preferred over scheduled."""
        fav_scheduled = self._game(detailed_state='Scheduled', away_team_id=133, home_team_id=147)
        fav_live = self._game(detailed_state='In Progress', away_team_id=111, home_team_id=147)
        result = select_game([fav_scheduled, fav_live], 'NYY', self.team_data)
        assert result is fav_live

    def test_favorite_scheduled_only(self):
        """Favorite scheduled only."""
        fav_scheduled = self._game(detailed_state='Scheduled', away_team_id=111, home_team_id=147)
        other_final = self._game(detailed_state='Final', away_team_id=133, home_team_id=999)
        result = select_game([other_final, fav_scheduled], 'BOS', self.team_data)
        assert result is fav_scheduled

    def test_favorite_not_playing_falls_back_to_live(self):
        """Favorite not playing falls back to live."""
        other_live = self._game(detailed_state='In Progress', away_team_id=133, home_team_id=999)
        result = select_game([other_live], 'NYY', self.team_data)
        assert result is other_live

    def test_favorite_abbr_unknown_falls_back(self):
        """favorite_abbr not present in team_abbreviation map at all."""
        live = self._game(detailed_state='In Progress')
        result = select_game([live], 'ZZZ', self.team_data)
        assert result is live

    def test_favorite_final_lowest_priority_but_still_preferred_over_nonfav_live(self):
        """A favorite game with a non-live/non-scheduled state (priority 3) is still
        chosen ahead of a non-favorite live game, since fav_games always wins."""
        fav_postponed = self._game(detailed_state='Postponed', away_team_id=111, home_team_id=147)
        other_live = self._game(detailed_state='In Progress', away_team_id=133, home_team_id=999)
        result = select_game([other_live, fav_postponed], 'BOS', self.team_data)
        assert result is fav_postponed

    def test_favorite_priority_ordering_live_beats_final(self):
        """Favorite priority ordering live beats final."""
        fav_final = self._game(detailed_state='Final', away_team_id=111, home_team_id=147)
        fav_live = self._game(detailed_state='In Progress', away_team_id=111, home_team_id=147)
        result = select_game([fav_final, fav_live], 'BOS', self.team_data)
        assert result is fav_live


# ===========================================================================
# fetch_live_feed — the only function that touches the network
# ===========================================================================

class TestFetchLiveFeed:
    @patch('game_detail_fetch.requests.get')
    def test_builds_url_and_returns_json(self, mock_get):
        """Builds url and returns json."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ok': True}
        mock_get.return_value = mock_resp
        result = fetch_live_feed(12345)
        mock_get.assert_called_once_with(
            'https://statsapi.mlb.com/api/v1.1/game/12345/feed/live', timeout=15,
        )
        mock_resp.raise_for_status.assert_called_once()
        assert result == {'ok': True}

    @patch('game_detail_fetch.requests.get')
    def test_raises_on_http_error(self, mock_get):
        """Raises on http error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = RuntimeError('boom')
        mock_get.return_value = mock_resp
        with pytest.raises(RuntimeError):
            fetch_live_feed(1)


# ===========================================================================
# _extract_pitches_detailed
# ===========================================================================

class TestExtractPitchesDetailed:
    def test_missing_pitch_data_returns_empty(self):
        """Missing pitch data returns empty."""
        plays = {'currentPlay': {'playEvents': [{'isPitch': True, 'pitchData': {}}]}, 'allPlays': []}
        assert _extract_pitches_detailed(plays) == []

    def test_no_events_at_all_returns_empty(self):
        """No events at all returns empty."""
        assert _extract_pitches_detailed({}) == []

    def test_non_pitch_events_skipped(self):
        """Non pitch events skipped."""
        plays = {'currentPlay': {'playEvents': [{'isPitch': False}]}, 'allPlays': []}
        assert _extract_pitches_detailed(plays) == []

    def test_current_play_pitches_extracted(self):
        """Current play pitches extracted."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': True, 'pitchData': {
                    'coordinates': {'pX': 0.1, 'pZ': 2.5}, 'strikeZoneTop': 3.4,
                    'strikeZoneBottom': 1.6, 'startSpeed': 94.2,
                }, 'details': {'type': {'code': 'FF', 'description': 'Four-Seam'},
                                'call': {'code': 'C'}, 'isStrike': True, 'isBall': False,
                                'description': 'Called Strike'}},
            ]},
            'allPlays': [],
        }
        pitches = _extract_pitches_detailed(plays)
        assert len(pitches) == 1
        assert pitches[0]['code'] == 'FF'
        assert pitches[0]['call'] == 'C'
        assert pitches[0]['speed'] == 94.2

    def test_falls_back_to_last_completed_play_when_current_empty(self):
        """Falls back to last completed play when current empty."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{'playEvents': [
                {'isPitch': True, 'pitchData': {'coordinates': {'pX': 0.0, 'pZ': 2.0}}},
            ]}],
        }
        pitches = _extract_pitches_detailed(plays)
        assert len(pitches) == 1


# ===========================================================================
# _count_abs_challenges_used / _count_replay_challenges_used
# ===========================================================================

class TestChallengeCounts:
    def test_no_team_ids_returns_zero_zero(self):
        """No team ids returns zero zero."""
        assert _count_abs_challenges_used({}, None, None) == (0, 0)
        assert _count_replay_challenges_used({}, None, None) == (0, 0)

    def test_abs_counts_pitch_reviews_by_team(self):
        """Abs counts pitch reviews by team."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 111}},
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 147}},
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 111}},
        ]}]}
        away, home = _count_abs_challenges_used(plays, 111, 147)
        assert (away, home) == (2, 1)

    def test_abs_skips_non_pitch_events(self):
        """Abs skips non pitch events."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'action', 'reviewDetails': {'challengeTeamId': 111}},
        ]}]}
        assert _count_abs_challenges_used(plays, 111, 147) == (0, 0)

    def test_abs_skips_in_progress_and_overturned(self):
        """Abs skips in progress and overturned."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 111, 'inProgress': True}},
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 111, 'isOverturned': True}},
        ]}]}
        assert _count_abs_challenges_used(plays, 111, 147) == (0, 0)

    def test_abs_no_review_details_skipped(self):
        """Abs no review details skipped."""
        plays = {'allPlays': [{'playEvents': [{'type': 'pitch'}]}]}
        assert _count_abs_challenges_used(plays, 111, 147) == (0, 0)

    def test_abs_unrelated_team_id_not_counted(self):
        """Abs unrelated team id not counted."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 999}},
        ]}]}
        assert _count_abs_challenges_used(plays, 111, 147) == (0, 0)

    def test_replay_counts_non_pitch_reviews_by_team(self):
        """Replay counts non pitch reviews by team."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'action', 'reviewDetails': {'challengeTeamId': 147}},
        ]}]}
        away, home = _count_replay_challenges_used(plays, 111, 147)
        assert (away, home) == (0, 1)

    def test_replay_skips_pitch_type(self):
        """Replay skips pitch type."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'pitch', 'reviewDetails': {'challengeTeamId': 147}},
        ]}]}
        assert _count_replay_challenges_used(plays, 111, 147) == (0, 0)

    def test_replay_skips_in_progress_and_overturned(self):
        """Replay skips in progress and overturned."""
        plays = {'allPlays': [{'playEvents': [
            {'type': 'action', 'reviewDetails': {'challengeTeamId': 147, 'inProgress': True}},
            {'type': 'action', 'reviewDetails': {'challengeTeamId': 147, 'isOverturned': True}},
        ]}]}
        assert _count_replay_challenges_used(plays, 111, 147) == (0, 0)


# ===========================================================================
# _last_name_simple
# ===========================================================================

class TestLastNameSimple:
    def test_jr_suffix(self):
        """Jr suffix."""
        assert _last_name_simple('Cal Ripken Jr.') == 'Ripken'

    def test_sr_suffix(self):
        """Sr suffix."""
        assert _last_name_simple('Ken Griffey Sr.') == 'Griffey'

    def test_ii_suffix(self):
        """Ii suffix."""
        assert _last_name_simple('Cecil Fielder II') == 'Fielder'

    def test_iii_suffix(self):
        """Iii suffix."""
        assert _last_name_simple('Felipe Lopez III') == 'Lopez'

    def test_no_suffix_returns_last_part(self):
        """No suffix returns last part."""
        assert _last_name_simple('Mookie Betts') == 'Betts'

    def test_single_name(self):
        """Single name."""
        assert _last_name_simple('Ohtani') == 'Ohtani'

    def test_empty_string(self):
        """Empty string."""
        assert _last_name_simple('') == ''

    def test_none(self):
        """None."""
        assert _last_name_simple(None) == ''

    def test_two_part_name_where_second_is_suffix_falls_through(self):
        """When the only 'other' part is itself a suffix, the loop never finds a
        non-suffix part and falls through to the final-part fallback."""
        assert _last_name_simple('Smith Jr.') == 'Jr.'


# ===========================================================================
# _find_recent_sub_event
# ===========================================================================

class TestFindRecentSubEvent:
    def test_no_subs_returns_none(self):
        """No subs returns none."""
        plays = {'currentPlay': {'playEvents': []}, 'allPlays': []}
        assert _find_recent_sub_event(plays) is None

    def test_fresh_mid_ab_pitching_change(self):
        """Fresh mid ab pitching change."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': False, 'details': {'eventType': 'pitching_substitution'},
                 'player': {'fullName': 'Jane Roe'}},
            ]},
            'allPlays': [],
        }
        assert _find_recent_sub_event(plays) == 'PC: Roe'

    def test_fresh_mid_ab_pinch_hitter(self):
        """Fresh mid ab pinch hitter."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': False, 'details': {'eventType': 'offensive_substitution',
                                                'description': 'Pinch hitter John Doe replaces X.'},
                 'player': {'fullName': 'John Doe'}},
            ]},
            'allPlays': [],
        }
        assert _find_recent_sub_event(plays) == 'PH: Doe'

    def test_offensive_substitution_without_pinch_ignored(self):
        """Offensive substitution without pinch ignored."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': False, 'details': {'eventType': 'offensive_substitution',
                                                'description': 'Defensive sub for Y.'},
                 'player': {'fullName': 'John Doe'}},
            ]},
            'allPlays': [],
        }
        assert _find_recent_sub_event(plays) is None

    def test_stale_mid_ab_sub_after_pitch_returns_none(self):
        """Sub occurred, then a pitch was thrown — no longer 'fresh'."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': False, 'details': {'eventType': 'pitching_substitution'},
                 'player': {'fullName': 'Jane Roe'}},
                {'isPitch': True, 'details': {}},
            ]},
            'allPlays': [],
        }
        assert _find_recent_sub_event(plays) is None

    def test_player_name_missing_is_skipped(self):
        """Player name missing is skipped."""
        plays = {
            'currentPlay': {'playEvents': [
                {'isPitch': False, 'details': {'eventType': 'pitching_substitution'}, 'player': {}},
            ]},
            'allPlays': [],
        }
        assert _find_recent_sub_event(plays) is None

    def test_between_ab_pitching_substitution(self):
        """Between ab pitching substitution."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{
                'result': {'eventType': 'pitching_substitution', 'description': ''},
                'matchup': {'pitcher': {'fullName': 'Jane Roe'}},
            }],
        }
        assert _find_recent_sub_event(plays) == 'PC: Roe'

    def test_between_ab_pinch_hitter(self):
        """Between ab pinch hitter."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{
                'result': {'eventType': 'offensive_substitution',
                           'description': 'Pinch hitter John Doe replaces Z.'},
                'matchup': {'batter': {'fullName': 'John Doe'}},
            }],
        }
        assert _find_recent_sub_event(plays) == 'PH: Doe'

    def test_between_ab_no_sub_returns_none(self):
        """Between ab no sub returns none."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{'result': {'eventType': 'Single', 'description': ''}, 'matchup': {}}],
        }
        assert _find_recent_sub_event(plays) is None

    def test_between_ab_stale_when_current_has_pitches(self):
        """A pitch has already been thrown in the current AB → sub isn't 'fresh'."""
        plays = {
            'currentPlay': {'playEvents': [{'isPitch': True, 'details': {}}]},
            'allPlays': [{
                'result': {'eventType': 'Pitching Substitution', 'description': ''},
                'matchup': {'pitcher': {'fullName': 'Jane Roe'}},
            }],
        }
        assert _find_recent_sub_event(plays) is None


# ===========================================================================
# _get_player_info
# ===========================================================================

class TestGetPlayerInfo:
    def test_none_player_id_returns_minimal_dict(self):
        """None player id returns minimal dict."""
        result = _get_player_info({}, None, 'batting')
        assert result == {'name': '', 'stats': {}}

    def test_zero_player_id_returns_minimal_dict(self):
        """Zero player id returns minimal dict."""
        result = _get_player_info({}, 0, 'batting')
        assert result == {'name': '', 'stats': {}}

    def test_found_via_id_key(self):
        """Found via id key."""
        boxscore = {'teams': {'away': {'players': {'ID9': {
            'person': {'id': 9, 'fullName': 'Mookie Betts'},
            'stats': {'batting': {'hits': 2}},
            'seasonStats': {'batting': {'hits': 80}},
        }}}, 'home': {'players': {}}}}
        result = _get_player_info(boxscore, 9, 'batting')
        assert result['name'] == 'Mookie Betts'
        assert result['stats'] == {'hits': 2}
        assert result['season'] == {'hits': 80}

    def test_found_via_person_id_fallback_when_key_mismatched(self):
        """The key doesn't match 'ID{player_id}' but person.id does — still matched."""
        boxscore = {'teams': {'away': {'players': {'IDweird': {
            'person': {'id': 9, 'fullName': 'Mookie Betts'},
            'stats': {'batting': {}},
        }}}, 'home': {'players': {}}}}
        result = _get_player_info(boxscore, 9, 'batting')
        assert result['name'] == 'Mookie Betts'

    def test_not_found_anywhere_returns_full_default(self):
        """Not found anywhere returns full default."""
        boxscore = {'teams': {'away': {'players': {}}, 'home': {'players': {}}}}
        result = _get_player_info(boxscore, 42, 'batting')
        assert result == {'name': '', 'stats': {}, 'season': {}}


# ===========================================================================
# fetch_scoreboard_live_extras
# ===========================================================================

class TestFetchScoreboardLiveExtras:
    @patch('game_detail_fetch.fetch_live_feed')
    def test_exception_returns_empty_dict(self, mock_fetch):
        """Exception returns empty dict."""
        mock_fetch.side_effect = RuntimeError('network down')
        assert fetch_scoreboard_live_extras(123) == {}

    @patch('game_detail_fetch.fetch_live_feed')
    def test_basic_fields_present(self, mock_fetch):
        """Basic fields present."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scoreboard_live_extras(123, away_id=111, home_id=147)
        assert result['pitch_count'] == 42
        assert result['batter_hits'] == 1
        assert result['batter_at_bats'] == 3
        assert result['due_up'] == 'Y'
        assert result['in_hole'] == 'Z'
        assert result['abs_challenge_max'] == 2

    @patch('game_detail_fetch.fetch_live_feed')
    def test_bat_side_and_pitch_hand_extracted_from_matchup(self, mock_fetch):
        """bat_side and pitch_hand come from currentPlay.matchup's batSide/
        pitchHand codes, for the batter/pitcher handedness suffixes."""
        feed = _live_feed()
        feed['liveData']['plays']['currentPlay']['matchup']['batSide'] = {'code': 'L'}
        feed['liveData']['plays']['currentPlay']['matchup']['pitchHand'] = {'code': 'R'}
        mock_fetch.return_value = feed
        result = fetch_scoreboard_live_extras(123)
        assert result['bat_side'] == 'L'
        assert result['pitch_hand'] == 'R'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_bat_side_and_pitch_hand_default_empty(self, mock_fetch):
        """Missing batSide/pitchHand in the matchup must not crash."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scoreboard_live_extras(123)
        assert result['bat_side'] == ''
        assert result['pitch_hand'] == ''

    @patch('game_detail_fetch.fetch_live_feed')
    def test_outs_this_half_defaults_empty(self, mock_fetch):
        """No completed outs yet in the current half-inning -> empty list."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scoreboard_live_extras(123)
        assert result['outs_this_half'] == []

    @patch('game_detail_fetch.fetch_live_feed')
    def test_outs_this_half_labels_recorded_out(self, mock_fetch):
        """A completed strikeout in the current (5th, top) half-inning shows up."""
        feed = _live_feed()
        feed['liveData']['plays']['allPlays'] = [
            _play(event='Strikeout', event_type='strikeout', inning=5, is_top=True,
                  play_events=[{'isPitch': True, 'details': {'call': {'code': 'S'}}}]),
        ]
        mock_fetch.return_value = feed
        result = fetch_scoreboard_live_extras(123)
        assert result['outs_this_half'] == ['K']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_runner_jersey_numbers(self, mock_fetch):
        """Runner jersey numbers."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scoreboard_live_extras(123)
        assert result['runner_first_number'] == '21'
        assert result['runner_second_number'] is None
        assert result['runner_third_number'] is None

    @patch('game_detail_fetch.fetch_live_feed')
    def test_abs_challenge_max_fixed_in_extra_innings(self, mock_fetch):
        """ABS challenge allotment does not grow in extra innings — it's a
        fixed 2 per team for the whole game, unlike the tennis-style
        challenge system some assume."""
        mock_fetch.return_value = _live_feed(liveData={'linescore': {'currentInning': 11}})
        result = fetch_scoreboard_live_extras(123)
        assert result['abs_challenge_max'] == 2

    @patch('game_detail_fetch.fetch_live_feed')
    def test_abs_challenge_max_tenth_inning(self, mock_fetch):
        """Abs challenge max tenth inning."""
        mock_fetch.return_value = _live_feed(liveData={'linescore': {'currentInning': 10}})
        result = fetch_scoreboard_live_extras(123)
        assert result['abs_challenge_max'] == 2

    @patch('game_detail_fetch.fetch_live_feed')
    def test_current_at_bat_pitch_tracking_swinging(self, mock_fetch):
        """Current at bat pitch tracking swinging."""
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [
                {'isPitch': True, 'pitchData': {'startSpeed': 95.0},
                 'details': {'call': {'code': 'S'}, 'type': {'code': 'FF'}}},
            ],
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert result['last_strike_call'] == 'S'
        assert result['strike_calls'] == ['S']
        assert result['last_pitch_type'] == 'FB'
        assert result['last_pitch_speed'] == 95.0
        assert result['at_bat_pitch_count'] == 1

    @patch('game_detail_fetch.fetch_live_feed')
    def test_current_at_bat_pitch_tracking_looking_and_foul(self, mock_fetch):
        """Current at bat pitch tracking looking and foul."""
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [
                {'isPitch': True, 'pitchData': {}, 'details': {'call': {'code': 'C'}, 'type': {'code': 'SL'}}},
                {'isPitch': True, 'pitchData': {}, 'details': {'call': {'code': 'F'}, 'type': {'code': 'CH'}}},
            ],
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert result['last_strike_call'] == 'F'
        assert result['strike_calls'] == ['C', 'F']
        assert result['last_pitch_type'] == 'CH'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_strike_calls_capped_at_two(self, mock_fetch):
        """Strike calls capped at two."""
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [
                {'isPitch': True, 'pitchData': {}, 'details': {'call': {'code': 'C'}, 'type': {}}},
                {'isPitch': True, 'pitchData': {}, 'details': {'call': {'code': 'C'}, 'type': {}}},
                {'isPitch': True, 'pitchData': {}, 'details': {'call': {'code': 'C'}, 'type': {}}},
            ],
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert len(result['strike_calls']) == 2

    @patch('game_detail_fetch.fetch_live_feed')
    def test_current_at_bat_complete_true_when_event_present(self, mock_fetch):
        """Current at bat complete true when event present."""
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'result': {'event': 'Single'},
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert result['current_at_bat_complete'] is True
        assert result['current_play_batter'] == 'Mookie Betts'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_current_at_bat_not_complete_when_no_event(self, mock_fetch):
        """Current at bat not complete when no event."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scoreboard_live_extras(123)
        assert result['current_at_bat_complete'] is False

    @patch('game_detail_fetch.fetch_live_feed')
    def test_batter_last_result_from_previous_at_bat(self, mock_fetch):
        """Batter last result from previous at bat."""
        prior_play = _play(event='Home Run', batter_id=1, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [prior_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['batter_last_result'] == 'HR'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_live_last_play_and_rbi_extracted(self, mock_fetch):
        """Live last play and rbi extracted."""
        scoring_play = _play(event='Home Run', batter_id=9, is_complete=True, rbi=2, inning=4, is_top=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [scoring_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['last_play'] == 'HR'
        assert result['last_play_rbi'] == 2
        assert result['last_play_inning'] == 4
        assert result['last_play_is_top'] is True

    @patch('game_detail_fetch.fetch_live_feed')
    def test_live_last_play_skips_substitution_events(self, mock_fetch):
        """Live last play skips substitution events."""
        sub_play = _play(event='Pitching Substitution', event_type='pitching_substitution', is_complete=True)
        real_play = _play(event='Single', batter_id=1, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [real_play, sub_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['last_play'] == '1B'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_live_last_play_skips_incomplete_plays(self, mock_fetch):
        """Live last play skips incomplete plays."""
        incomplete = _play(event='Single', is_complete=False)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [incomplete]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['last_play'] is None

    @patch('game_detail_fetch.fetch_live_feed')
    def test_last_review_result_uses_team_abbrs_from_gamedata(self, mock_fetch):
        """Last review result uses team abbrs from gamedata."""
        review_event = {
            'isPitch': False,
            'reviewDetails': {'isOverturned': True, 'inProgress': False, 'challengeTeamId': 111},
            'details': {'description': 'Review completed.'},
        }
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [review_event],
        }}})
        result = fetch_scoreboard_live_extras(123, away_id=111, home_id=147)
        assert result['last_review_result'] == 'OVR BOS'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_sub_event_surfaced(self, mock_fetch):
        """Sub event surfaced."""
        sub_ev = {'isPitch': False, 'details': {'eventType': 'pitching_substitution'},
                   'player': {'fullName': 'Jane Roe'}}
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [sub_ev],
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert result['sub_event'] == 'PC: Roe'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_ab_pitches_have_pt_abbr(self, mock_fetch):
        """Ab pitches have pt abbr."""
        pitch_ev = {'isPitch': True, 'pitchData': {'coordinates': {'pX': 0.1, 'pZ': 2.0}},
                    'details': {'type': {'code': 'SL'}}}
        mock_fetch.return_value = _live_feed(liveData={'plays': {'currentPlay': {
            'playEvents': [pitch_ev],
        }}})
        result = fetch_scoreboard_live_extras(123)
        assert result['ab_pitches'][0]['pt_abbr'] == 'SL'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_includes_half_inning_marker(self, mock_fetch):
        """Half inning plays includes half inning marker."""
        top_play = _play(event='Single', batter_id=1, is_top=True, inning=1, is_complete=True)
        bottom_play = _play(event='Groundout', batter_id=2, is_top=False, inning=1, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [top_play, bottom_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'v' in result['half_inning_plays']  # heading into bottom half

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_action_code_stolen_base(self, mock_fetch):
        """Half inning plays action code stolen base."""
        play_with_action = _play(event='Single', batter_id=1, is_complete=True, play_events=[
            {'type': 'action', 'details': {'eventType': 'stolen_base'}},
        ])
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [play_with_action]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'SB' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_review_action(self, mock_fetch):
        """Half inning plays review action."""
        play_with_review = _play(event='Single', batter_id=1, is_complete=True, play_events=[
            {'reviewDetails': {'isOverturned': False, 'inProgress': False}},
        ])
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [play_with_review]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'CHAL L' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_grand_slam_label(self, mock_fetch):
        """Half inning plays grand slam label."""
        hr_play = _play(event='Home Run', batter_id=1, rbi=4, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [hr_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'Grand Slam' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_two_run_hr_label(self, mock_fetch):
        """Half inning plays two run hr label."""
        hr_play = _play(event='Home Run', batter_id=1, rbi=2, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [hr_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert '2R HR' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_solo_hr_no_prefix(self, mock_fetch):
        """Half inning plays solo hr no prefix."""
        hr_play = _play(event='Home Run', batter_id=1, rbi=1, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [hr_play]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'HR' in result['half_inning_plays']
        assert 'RBI HR' not in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_single_rbi_prefix(self, mock_fetch):
        """Half inning plays single rbi prefix."""
        play = _play(event='Single', batter_id=1, rbi=1, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [play]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'RBI 1B' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_multi_rbi_prefix(self, mock_fetch):
        """Half inning plays multi rbi prefix."""
        play = _play(event='Double', batter_id=1, rbi=3, is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [play]}})
        result = fetch_scoreboard_live_extras(123)
        assert '3RBI 2B' in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_error_not_prefixed_with_rbi(self, mock_fetch):
        """Half inning plays error not prefixed with rbi."""
        play = _play(event='Field Error', batter_id=1, rbi=1, is_complete=True,
                      credits=[{'position': {'code': '6'}, 'credit': 'f_error'}])
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [play]}})
        result = fetch_scoreboard_live_extras(123)
        assert 'E6' in result['half_inning_plays']
        assert 'RBI E6' not in result['half_inning_plays']

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_pitching_substitution_dedup(self, mock_fetch):
        """Half inning plays pitching substitution dedup."""
        sub1 = _play(event='Pitching Substitution', event_type='pitching_substitution', is_complete=True)
        sub2 = _play(event='Pitching Substitution', event_type='pitching_substitution', is_complete=True)
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [sub1, sub2]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['half_inning_plays'].count('PC') == 1

    @patch('game_detail_fetch.fetch_live_feed')
    def test_half_inning_plays_capped_at_seven_events(self, mock_fetch):
        """Half inning plays capped at seven events."""
        plays = [_play(event='Single', batter_id=i, is_complete=True, inning=1) for i in range(10)]
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': plays}})
        result = fetch_scoreboard_live_extras(123)
        real_events = [t for t in result['half_inning_plays'] if t not in ('^', 'v')]
        assert len(real_events) == 7

    @patch('game_detail_fetch.fetch_live_feed')
    def test_pitcher_ks_swinging_and_looking(self, mock_fetch):
        """Pitcher ks swinging and looking."""
        k_swing = _play(event='Strikeout', event_type='strikeout', is_top=True, is_complete=True,
                         play_events=[{'isPitch': True, 'details': {'code': 'S'}}])
        k_look = _play(event='Strikeout', event_type='strikeout', is_top=False, is_complete=True,
                        play_events=[{'isPitch': True, 'details': {'code': 'C'}}])
        mock_fetch.return_value = _live_feed(liveData={'plays': {'allPlays': [k_swing, k_look]}})
        result = fetch_scoreboard_live_extras(123)
        assert result['home_pitcher_ks'] == ['K']
        assert result['away_pitcher_ks'] == ['L']


# ===========================================================================
# fetch_between_inning_info
# ===========================================================================

class TestFetchBetweenInningInfo:
    @patch('game_detail_fetch.fetch_live_feed')
    def test_exception_returns_empty_dict(self, mock_fetch):
        """Exception returns empty dict."""
        mock_fetch.side_effect = RuntimeError('boom')
        assert fetch_between_inning_info(123, 'Middle') == {}

    @patch('game_detail_fetch.fetch_live_feed')
    def test_no_batting_order_data_returns_empty(self, mock_fetch):
        """No batting order data returns empty."""
        mock_fetch.return_value = _live_feed(liveData={
            'boxscore': {'teams': {'away': {'players': {}, 'battingOrder': []},
                                    'home': {'players': {}, 'battingOrder': []}}},
            'plays': {'allPlays': []},
        })
        assert fetch_between_inning_info(123, 'Middle') == {}

    @patch('game_detail_fetch.fetch_live_feed')
    def test_builds_order_from_plays_middle_state(self, mock_fetch):
        """inningState='Middle' -> home bats next; batting order built from bottom-half plays."""
        p1 = _play(event='Single', batter_id=5, batter_name='Logan Webb', is_top=False, half='bottom')
        p2 = _play(event='Groundout', batter_id=2, batter_name='X', is_top=False, half='bottom')
        feed = _live_feed(liveData={'plays': {'allPlays': [p1, p2]}})
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        assert result['next_batter_1'] != ''
        assert result['next_pitcher'] == 'Reid Ray' or result['next_pitcher'] == 'Logan Webb'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_fallback_batting_order_field_when_no_plays(self, mock_fetch):
        """Team hasn't batted yet (e.g. home team, Middle of 1st) -> use battingOrder field."""
        feed = _live_feed(liveData={'plays': {'allPlays': []}})
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        # Home team's boxscore battingOrder=[5] with battingOrder field '900' -> slot 9
        assert result != {}

    @patch('game_detail_fetch.fetch_live_feed')
    def test_pitcher_name_fallback_via_boxscore_lookup(self, mock_fetch):
        """linescore.defense.pitcher has no fullName -> look up via boxscore players."""
        feed = _live_feed(liveData={
            'linescore': {'defense': {'pitcher': {'id': 5}}},
            'plays': {'allPlays': []},
        })
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        assert result.get('next_pitcher') == 'Logan Webb'

    @patch('game_detail_fetch.fetch_live_feed')
    def test_last_play_notation_from_ended_half(self, mock_fetch):
        """inning_state='Middle' -> the half that just ended is 'top'."""
        ended_play = _play(event='Home Run', batter_id=1, is_top=True, half='top', is_complete=True)
        feed = _live_feed(liveData={'plays': {'allPlays': [ended_play]}})
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        assert result.get('last_play') == 'HR'
        assert result.get('last_play_is_top') is True

    @patch('game_detail_fetch.fetch_live_feed')
    def test_last_play_notation_ignored_when_wrong_half(self, mock_fetch):
        """A completed play from the 'bottom' half must not surface when the ended half is 'top'."""
        wrong_half_play = _play(event='Home Run', batter_id=1, is_top=False, half='bottom', is_complete=True)
        feed = _live_feed(liveData={'plays': {'allPlays': [wrong_half_play]}})
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        assert result.get('last_play') is None

    @patch('game_detail_fetch.fetch_live_feed')
    def test_end_state_away_bats_next(self, mock_fetch):
        """End state away bats next."""
        p1 = _play(event='Single', batter_id=1, batter_name='Mookie Betts', is_top=True, half='top')
        feed = _live_feed(liveData={'plays': {'allPlays': [p1]}})
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'End')
        assert result != {}

    @patch('game_detail_fetch.fetch_live_feed')
    def test_subbed_out_last_batter_resolves_via_batting_order_field(self, mock_fetch):
        """last_batter_pid not in ordered_pids -> resolve slot via battingOrder field."""
        p1 = _play(event='Single', batter_id=1, is_top=False, half='bottom')
        p2 = _play(event='Groundout', batter_id=99, is_top=False, half='bottom')  # subbed-in batter
        feed = _live_feed(liveData={'plays': {'allPlays': [p1, p2]}})
        # add player 99 to home roster with a battingOrder field but not in original lineup order
        feed['liveData']['boxscore']['teams']['home']['players']['ID99'] = {
            'person': {'id': 99, 'fullName': 'Sub Guy'}, 'battingOrder': '200',
        }
        mock_fetch.return_value = feed
        result = fetch_between_inning_info(123, 'Middle')
        assert result != {}


# ===========================================================================
# _extract_all_hit_coordinates
# ===========================================================================

class TestExtractAllHitCoordinates:
    def test_no_plays_returns_empty(self):
        """No plays returns empty."""
        assert _extract_all_hit_coordinates({'allPlays': []}) == []

    def test_hit_from_top_level_hit_data(self):
        """Hit from top level hit data."""
        play = _play(event='Single', batter_name='Mookie Betts',
                      hit_data={'coordinates': {'coordX': 100.0, 'coordY': 150.0}})
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert len(result) == 1
        assert result[0]['is_hit'] is True
        assert result[0]['is_hr'] is False
        assert result[0]['player'] == 'Betts'

    def test_home_run_flags(self):
        """Home run flags."""
        play = _play(event='Home Run', batter_name='Aaron Judge',
                      hit_data={'coordinates': {'coordX': 50.0, 'coordY': 30.0}})
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert result[0]['is_hr'] is True
        assert result[0]['is_hit'] is True
        assert result[0]['is_out'] is False

    def test_out_event_flagged_is_out(self):
        """Out event flagged is out."""
        play = _play(event='Groundout', batter_name='X',
                      hit_data={'coordinates': {'coordX': 10.0, 'coordY': 20.0}})
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert result[0]['is_out'] is True
        assert result[0]['is_hit'] is False

    def test_fallback_to_play_events_hit_data(self):
        """Fallback to play events hit data."""
        play = _play(event='Double', batter_name='Y', hit_data={},
                      play_events=[{'details': {'isInPlay': True},
                                    'hitData': {'coordinates': {'coordX': 5.0, 'coordY': 6.0}}}])
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert len(result) == 1
        assert result[0]['x'] == 5.0

    def test_no_coordinates_anywhere_skips_play(self):
        """No coordinates anywhere skips play."""
        play = _play(event='Single', batter_name='Z', hit_data={}, play_events=[{'hitData': {}}])
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert result == []

    def test_multiple_hits_chronological(self):
        """Multiple hits chronological."""
        p1 = _play(event='Single', batter_name='A', hit_data={'coordinates': {'coordX': 1.0, 'coordY': 1.0}})
        p2 = _play(event='Double', batter_name='B', hit_data={'coordinates': {'coordX': 2.0, 'coordY': 2.0}})
        result = _extract_all_hit_coordinates({'allPlays': [p1, p2]})
        assert [r['player'] for r in result] == ['A', 'B']

    def test_missing_batter_name_gives_empty_last_name(self):
        """Missing batter name gives empty last name."""
        play = {
            'result': {'event': 'Single'}, 'about': {},
            'matchup': {'batter': {}},
            'hitData': {'coordinates': {'coordX': 1.0, 'coordY': 1.0}},
            'playEvents': [],
        }
        result = _extract_all_hit_coordinates({'allPlays': [play]})
        assert result[0]['player'] == ''


# ===========================================================================
# _build_lineup_at_bats
# ===========================================================================

class TestBuildLineupAtBats:
    def _boxscore(self):
        """Boxscore."""
        return {
            'teams': {
                'away': {
                    'battingOrder': [1, 2],
                    'team': {'id': 111},
                    'players': {
                        'ID1': {'person': {'id': 1, 'fullName': 'Player One'},
                                'position': {'abbreviation': 'RF'}, 'battingOrder': '100',
                                'stats': {'batting': {'runs': 1, 'hits': 2}}},
                        'ID2': {'person': {'id': 2, 'fullName': 'Player Two'},
                                'position': {'abbreviation': 'LF'}, 'battingOrder': '200',
                                'stats': {'batting': {'runs': 0, 'hits': 1}}},
                    },
                },
            },
        }

    def test_basic_lineup_built(self):
        """Basic lineup built."""
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': []}, 'away')
        assert len(lineup) == 2
        assert lineup[0]['name'] == 'Player One'
        assert lineup[0]['order'] == 1

    def test_substitution_detected(self):
        """Substitution detected."""
        boxscore = self._boxscore()
        # Add a sub who has the same batting order slot (1) — appears later in battingOrder list
        boxscore['teams']['away']['battingOrder'] = [1, 3]
        boxscore['teams']['away']['players']['ID3'] = {
            'person': {'id': 3, 'fullName': 'Sub Guy'},
            'position': {'abbreviation': 'RF'}, 'battingOrder': '100',
            'stats': {'batting': {}},
        }
        lineup, totals = _build_lineup_at_bats(boxscore, {'allPlays': []}, 'away')
        assert lineup[0]['sub'] is True
        assert lineup[0]['sub_original']['name'] == 'Player One'

    def test_at_bat_assigned_to_correct_slot(self):
        """At bat assigned to correct slot."""
        play = _play(event='Single', batter_id=1, is_top=True, half='top', inning=1,
                      play_events=[{'isPitch': True, 'details': {'isBall': True}},
                                   {'isPitch': True, 'details': {'isStrike': True}}])
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        at_bats = lineup[0]['at_bats'][1]
        assert at_bats[0]['code'] == '1B'
        assert at_bats[0]['bases'] == 1
        assert at_bats[0]['balls'] == 1
        assert at_bats[0]['strikes'] == 1

    def test_home_run_bases_four(self):
        """Home run bases four."""
        play = _play(event='Home Run', batter_id=1, is_top=True, half='top', inning=1)
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        assert lineup[0]['at_bats'][1][0]['bases'] == 4

    def test_walk_and_hbp_bases_one(self):
        """Walk and hbp bases one."""
        for ev in ('Walk', 'Intent Walk', 'Hit By Pitch'):
            play = _play(event=ev, batter_id=1, is_top=True, half='top', inning=1)
            lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
            assert lineup[0]['at_bats'][1][0]['bases'] == 1

    def test_wrong_half_inning_play_ignored(self):
        """Wrong half inning play ignored."""
        play = _play(event='Single', batter_id=1, is_top=False, half='bottom', inning=1)
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        assert lineup[0]['at_bats'] == {}

    def test_batter_id_none_skipped(self):
        """Batter id none skipped."""
        play = {
            'result': {'event': 'Single'}, 'about': {'inning': 1, 'halfInning': 'top'},
            'matchup': {'batter': {}}, 'playEvents': [], 'runners': [],
        }
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        assert lineup[0]['at_bats'] == {}

    def test_unmapped_event_code_skips_play(self):
        """Unmapped event code skips play."""
        play = _play(event='', batter_id=1, is_top=True, half='top', inning=1)
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        assert lineup[0]['at_bats'] == {}

    def test_inning_totals_counts_scoring_runners(self):
        """Inning totals counts scoring runners."""
        play = _play(event='Single', batter_id=1, is_top=True, half='top', inning=1)
        play['runners'] = [{'movement': {'end': 'score'}}, {'movement': {'end': '1B'}}]
        lineup, totals = _build_lineup_at_bats(self._boxscore(), {'allPlays': [play]}, 'away')
        assert totals[1] == 1

    def test_batter_subbed_out_resolves_via_batting_order(self):
        """Batter not in the final lineup (was replaced) — still assigned via battingOrder slot."""
        boxscore = self._boxscore()
        # Player 1 gets subbed out by player 3 in the same slot
        boxscore['teams']['away']['battingOrder'] = [3, 2]
        boxscore['teams']['away']['players']['ID3'] = {
            'person': {'id': 3, 'fullName': 'Sub Guy'},
            'position': {'abbreviation': 'RF'}, 'battingOrder': '100',
            'stats': {'batting': {}},
        }
        # But an at-bat happened for player 1 (before the sub)
        boxscore['teams']['away']['players']['ID1']['battingOrder'] = '100'
        play = _play(event='Single', batter_id=1, is_top=True, half='top', inning=1)
        lineup, totals = _build_lineup_at_bats(boxscore, {'allPlays': [play]}, 'away')
        assert lineup[0]['at_bats'].get(1, [{}])[0].get('code') == '1B'


# ===========================================================================
# _extract_pitchers
# ===========================================================================

class TestExtractPitchers:
    def test_basic_extraction(self):
        """Basic extraction."""
        boxscore = {'teams': {'away': {
            'pitchers': [5],
            'players': {'ID5': {'person': {'fullName': 'Logan Webb'},
                                 'stats': {'pitching': {'inningsPitched': '6.0', 'hits': 3,
                                                         'earnedRuns': 1, 'strikeOuts': 7}}}},
        }}}
        pitchers = _extract_pitchers(boxscore, 'away')
        assert pitchers == [{'name': 'Webb', 'ip': '6.0', 'hits': 3, 'er': 1, 'k': 7}]

    def test_pitcher_not_in_players_dict(self):
        """Pitcher not in players dict."""
        boxscore = {'teams': {'away': {'pitchers': [99], 'players': {}}}}
        pitchers = _extract_pitchers(boxscore, 'away')
        assert pitchers == [{'name': '', 'ip': '0.0', 'hits': 0, 'er': 0, 'k': 0}]

    def test_empty_pitchers_list(self):
        """Empty pitchers list."""
        boxscore = {'teams': {'away': {'pitchers': [], 'players': {}}}}
        assert _extract_pitchers(boxscore, 'away') == []


# ===========================================================================
# fetch_scorecard_data
# ===========================================================================

class TestFetchScorecardData:
    @patch('game_detail_fetch.fetch_live_feed')
    def test_happy_path(self, mock_fetch):
        """Happy path."""
        mock_fetch.return_value = _live_feed()
        result = fetch_scorecard_data(123)
        assert result['away_abbr'] == 'BOS'
        assert result['home_abbr'] == 'NYY'
        assert result['num_innings'] == 9  # max(len(innings)=2, 9)
        assert len(result['away_pitchers']) == 1 or result['away_pitchers'] == []
        assert isinstance(result['away_lineup'], list)

    @patch('game_detail_fetch.fetch_live_feed')
    def test_num_innings_extends_beyond_nine(self, mock_fetch):
        """Num innings extends beyond nine."""
        innings = [{'num': i, 'away': {'runs': 0}, 'home': {'runs': 0}} for i in range(1, 12)]
        mock_fetch.return_value = _live_feed(liveData={'linescore': {'innings': innings}})
        result = fetch_scorecard_data(123)
        assert result['num_innings'] == 11


# ===========================================================================
# _map_event_to_code
# ===========================================================================

class TestMapEventToCode:
    def test_known_event(self):
        """Known event."""
        assert _map_event_to_code('Strikeout') == 'K'
        assert _map_event_to_code('Home Run') == 'HR'
        assert _map_event_to_code('Field Error') == 'E'

    def test_unknown_event_falls_back_to_first_three_chars(self):
        """Unknown event falls back to first three chars."""
        assert _map_event_to_code('Bunt Groundout') == 'Bun'

    def test_empty_event_returns_empty(self):
        """Empty event returns empty."""
        assert _map_event_to_code('') == ''

    def test_none_event_returns_empty(self):
        """None event returns empty."""
        assert _map_event_to_code(None) == ''


# ===========================================================================
# _pos_from_desc
# ===========================================================================

class TestPosFromDesc:
    def test_none_returns_empty(self):
        """None returns empty."""
        assert _pos_from_desc(None) == ''

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _pos_from_desc('') == ''

    def test_no_match_returns_empty(self):
        """No match returns empty."""
        assert _pos_from_desc('Strikeout swinging') == ''

    @pytest.mark.parametrize('desc,expected', [
        ('flyball to center fielder', '8'),
        ('flyball to right fielder', '9'),
        ('flyball to left fielder', '7'),
        ('groundball to first baseman', '3'),
        ('groundball to second baseman', '4'),
        ('groundball to third baseman', '5'),
        ('lineout to shortstop', '6'),
        ('popup to catcher', '2'),
        ('comebacker to pitcher', '1'),
    ])
    def test_each_position_keyword(self, desc, expected):
        """Each position keyword."""
        assert _pos_from_desc(desc) == expected

    def test_case_insensitive(self):
        """Case insensitive."""
        assert _pos_from_desc('FLYBALL TO CENTER FIELDER') == '8'


# ===========================================================================
# _build_scorecard_notation — branches not already covered by
# test_scoreboard_rules.py (lineout/popout/sac fly/sac bunt/FC, description
# fallback fielder sequence, and the generic _EVENT_CODE_MAP fallback).
# ===========================================================================

class TestBuildScorecardNotationExtra:
    def _play(self, event, credits=None, description=''):
        """Play."""
        return {
            'result': {'event': event, 'eventType': '', 'description': description},
            'credits': credits or [],
            'playEvents': [],
        }

    def _credit(self, pos, credit_type):
        """Credit."""
        return {'position': {'code': pos}, 'credit': credit_type}

    def test_lineout_with_putout(self):
        """Lineout with putout."""
        play = self._play('Lineout', credits=[self._credit('6', 'f_putout')])
        assert _build_scorecard_notation(play) == 'L6'

    def test_lineout_no_credits_description_fallback(self):
        """Lineout no credits description fallback."""
        play = self._play('Lineout', description='Lines out to the shortstop.')
        assert _build_scorecard_notation(play) == 'L6'

    def test_lineout_no_credits_no_desc_match(self):
        """Lineout no credits no desc match."""
        play = self._play('Lineout', description='')
        assert _build_scorecard_notation(play) == 'LO'

    def test_popout_with_putout(self):
        """Popout with putout."""
        play = self._play('Pop Out', credits=[self._credit('2', 'f_putout')])
        assert _build_scorecard_notation(play) == 'P2'

    def test_popout_description_fallback(self):
        """Popout description fallback."""
        play = self._play('Popout', description='Pops out to the catcher.')
        assert _build_scorecard_notation(play) == 'P2'

    def test_popout_no_match_returns_PO(self):
        """Popout no match returns PO."""
        play = self._play('Pop Out', description='')
        assert _build_scorecard_notation(play) == 'PO'

    def test_sac_fly_with_putout(self):
        """Sac fly with putout."""
        play = self._play('Sac Fly', credits=[self._credit('8', 'f_putout')])
        assert _build_scorecard_notation(play) == 'SF8'

    def test_sac_fly_no_credits_returns_SF(self):
        """Sac fly no credits returns SF."""
        play = self._play('Sac Fly', description='')
        assert _build_scorecard_notation(play) == 'SF'

    def test_sac_bunt_with_sequence(self):
        """Sac bunt with sequence."""
        play = self._play('Sac Bunt', credits=[
            self._credit('1', 'f_assist'), self._credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == 'SAC 1-3'

    def test_sac_bunt_no_credits_returns_SAC(self):
        """Sac bunt no credits returns SAC."""
        play = self._play('Sac Bunt')
        assert _build_scorecard_notation(play) == 'SAC'

    def test_fielders_choice_with_sequence(self):
        """Fielders choice with sequence."""
        play = self._play('Fielders Choice', credits=[self._credit('6', 'f_assist')])
        assert _build_scorecard_notation(play) == '6 FC'

    def test_fielders_choice_no_credits_returns_FC(self):
        """Fielders choice no credits returns FC."""
        play = self._play('Fielders Choice')
        assert _build_scorecard_notation(play) == 'FC'

    def test_generic_out_description_fallback_sequence(self):
        """No credits at all -> parse fielder keywords out of the description."""
        play = self._play('Groundout', description='Ground ball, shortstop to first baseman.')
        assert _build_scorecard_notation(play) == '6-3'

    def test_caught_stealing_description_fallback(self):
        """Caught stealing description fallback."""
        play = self._play('Caught Stealing 2B',
                           description='Caught stealing, catcher to shortstop.')
        result = _build_scorecard_notation(play)
        assert result == 'CS 2-6'

    def test_pickoff_description_fallback(self):
        """Pickoff description fallback."""
        play = self._play('Pickoff 1B', description='Picked off, pitcher to first baseman.')
        result = _build_scorecard_notation(play)
        assert result == 'PO 1-3'

    def test_strikeout_double_play_description_fallback(self):
        """Strikeout double play description fallback."""
        play = self._play('Strikeout Double Play',
                           description='Strikes out, catcher to first baseman.')
        result = _build_scorecard_notation(play)
        assert result == 'K 2-3'

    def test_unmapped_event_with_no_credits_no_desc_falls_back_to_event_code_map(self):
        """Unmapped event with no credits no desc falls back to event code map."""
        play = self._play('Batter Interference')
        assert _build_scorecard_notation(play) == 'BI'

    def test_completely_unknown_event_falls_back_to_first_three_chars(self):
        """Completely unknown event falls back to first three chars."""
        play = self._play('Some Weird Event')
        assert _build_scorecard_notation(play) == 'Som'

    def test_generic_out_no_credits_no_desc_match_falls_back(self):
        """Groundout with no credits and a description with no fielder keywords."""
        play = self._play('Groundout', description='')
        # _EVENT_CODE_MAP has no 'Groundout' fallback via _map (only via _EVENT_CODE_MAP dict directly)
        result = _build_scorecard_notation(play)
        assert result == 'GO'


# ===========================================================================
# _build_current_half_inning_outs — per-out play-type labels (K, F8, ...)
# for the wide-cell's out circles.
# ===========================================================================

class TestBuildCurrentHalfInningOuts:
    def test_no_current_play_no_all_plays_returns_empty(self):
        """No current play no all plays returns empty."""
        assert _build_current_half_inning_outs({'currentPlay': {}, 'allPlays': []}) == []

    def test_strikeout_then_flyout_labelled_in_order(self):
        """Strikeout then flyout labelled in order."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='Strikeout', event_type='strikeout', inning=7, is_top=True,
                      play_events=[{'isPitch': True, 'details': {'call': {'code': 'S'}}}]),
                _play(event='Flyout', event_type='field_out', inning=7, is_top=True,
                      credits=[{'position': {'code': '8'}, 'credit': 'f_putout'}]),
            ],
        }
        assert _build_current_half_inning_outs(plays) == ['K', 'F8']

    def test_ignores_plays_from_other_half_innings(self):
        """A completed play from a different inning/half must not be counted."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='Strikeout', event_type='strikeout', inning=6, is_top=False),
                _play(event='Groundout', event_type='field_out', inning=7, is_top=True,
                      credits=[{'position': {'code': '3'}, 'credit': 'f_putout'}]),
            ],
        }
        assert _build_current_half_inning_outs(plays) == ['3']

    def test_incomplete_current_play_not_counted(self):
        """The at-bat in progress hasn't recorded an out yet — must not appear."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='', event_type='', inning=7, is_top=True, is_complete=False),
            ],
        }
        assert _build_current_half_inning_outs(plays) == []

    def test_non_out_events_not_counted(self):
        """Hits, walks, and other non-out events don't produce an out label."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='Single', event_type='single', inning=7, is_top=True),
                _play(event='Walk', event_type='walk', inning=7, is_top=True),
            ],
        }
        assert _build_current_half_inning_outs(plays) == []

    def test_double_play_labels_both_outs_with_same_notation(self):
        """A double play records 2 outs on one play — both slots get its notation."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='Grounded Into DP', event_type='grounded_into_double_play',
                      inning=7, is_top=True,
                      credits=[{'position': {'code': '6'}, 'credit': 'f_assist'},
                               {'position': {'code': '4'}, 'credit': 'f_assist'},
                               {'position': {'code': '3'}, 'credit': 'f_putout'}]),
            ],
        }
        assert _build_current_half_inning_outs(plays) == ['6-4-3 DP', '6-4-3 DP']

    def test_result_capped_at_three_outs(self):
        """Never returns more than 3 labels even if the data implies more."""
        plays = {
            'currentPlay': {'about': {'inning': 7, 'isTopInning': True}},
            'allPlays': [
                _play(event='Strikeout', event_type='strikeout', inning=7, is_top=True),
                _play(event='Grounded Into DP', event_type='grounded_into_double_play',
                      inning=7, is_top=True,
                      credits=[{'position': {'code': '6'}, 'credit': 'f_putout'}]),
            ],
        }
        assert len(_build_current_half_inning_outs(plays)) == 3

    def test_falls_back_to_last_all_play_when_current_play_has_no_about(self):
        """Between-innings frames: currentPlay may lack 'about' — use the last
        completed play in allPlays to identify the half-inning instead."""
        plays = {
            'currentPlay': {},
            'allPlays': [
                _play(event='Flyout', event_type='field_out', inning=3, is_top=False,
                      credits=[{'position': {'code': '9'}, 'credit': 'f_putout'}]),
            ],
        }
        assert _build_current_half_inning_outs(plays) == ['F9']


# ===========================================================================
# _find_recent_review_result — branch not covered by test_scoreboard_rules.py:
# no pitches yet in currentPlay -> check the last completed play in allPlays.
# ===========================================================================

class TestFindRecentReviewResultAllPlaysFallback:
    def test_falls_back_to_last_completed_play_when_current_ab_has_no_pitches(self):
        """Falls back to last completed play when current ab has no pitches."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{
                'playEvents': [{
                    'isPitch': False,
                    'reviewDetails': {'isOverturned': False, 'inProgress': False},
                    'details': {'description': 'Manager challenge (strike): Call confirmed.'},
                }],
            }],
        }
        result = _find_recent_review_result(plays)
        assert result == 'CFM: Strike'

    def test_no_fallback_when_current_ab_already_has_pitches(self):
        """If the current AB already has pitches, we must not look at allPlays at all."""
        plays = {
            'currentPlay': {'playEvents': [{'isPitch': True, 'details': {}}]},
            'allPlays': [{
                'playEvents': [{
                    'isPitch': False,
                    'reviewDetails': {'isOverturned': False, 'inProgress': False},
                    'details': {'description': 'Manager challenge (strike): Call confirmed.'},
                }],
            }],
        }
        assert _find_recent_review_result(plays) is None

    def test_allplays_fallback_skips_in_progress_review(self):
        """Allplays fallback skips in progress review."""
        plays = {
            'currentPlay': {'playEvents': []},
            'allPlays': [{
                'playEvents': [{
                    'isPitch': False,
                    'reviewDetails': {'isOverturned': False, 'inProgress': True},
                    'details': {'description': ''},
                }],
            }],
        }
        assert _find_recent_review_result(plays) is None
