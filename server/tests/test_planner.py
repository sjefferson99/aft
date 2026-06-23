"""Tests for the year/month planner API endpoints."""
from datetime import datetime, timedelta

import pytest


def get_current_user(api_client, session):
    response = session.get(f'{api_client}/api/auth/me')
    assert response.status_code == 200
    return response.json()['user']


def _create_card(api_client, session, column_id, **kwargs):
    payload = {'title': kwargs.pop('title', 'Planner test card')}
    payload.update(kwargs)
    response = session.post(f'{api_client}/api/columns/{column_id}/cards', json=payload)
    assert response.status_code == 201, response.text
    return response.json()['card']


@pytest.mark.api
class TestYearPlannerEndpoint:
    def test_busy_day_marked_for_card_with_start_and_end_date(self, api_client, authenticated_session, sample_column):
        year = datetime.now().year
        _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-06-15T09:00:00Z',
            end_date=f'{year}-06-15T10:00:00Z',
        )

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/year/{year}')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['year'] == year

        june = next(m for m in data['months'] if m['month'] == 6)
        assert 15 in june['busy_days']

        july = next(m for m in data['months'] if m['month'] == 7)
        assert 15 not in july['busy_days']

    def test_scheduled_only_day_appears_in_scheduled_days_not_busy_days(self, api_client, authenticated_session, sample_column):
        template = _create_card(api_client, authenticated_session, sample_column['id'], title='Daily template')
        tomorrow = datetime.now() + timedelta(days=1)
        schedule_response = authenticated_session.post(f'{api_client}/api/schedules', json={
            'card_id': template['id'],
            'keep_source_card': True,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow.strftime('%Y-%m-%dT%H:%M:%S'),
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
        })
        assert schedule_response.status_code == 201, schedule_response.text

        response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_column["board_id"]}/planner/year/{tomorrow.year}?include_scheduled=true'
        )
        assert response.status_code == 200
        month_data = next(m for m in response.json()['months'] if m['month'] == tomorrow.month)
        assert tomorrow.day in month_data['scheduled_days']
        assert tomorrow.day not in month_data['busy_days']

    def test_card_without_end_date_only_marks_start_day(self, api_client, authenticated_session, sample_column):
        year = datetime.now().year
        _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-09-10T09:00:00Z',
        )

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/year/{year}')
        assert response.status_code == 200
        september = next(m for m in response.json()['months'] if m['month'] == 9)
        assert september['busy_days'] == [10]


@pytest.mark.api
class TestMonthPlannerEndpoint:
    def test_card_spanning_month_boundary_appears_in_both_months(self, api_client, authenticated_session, sample_column):
        year = datetime.now().year
        card = _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-06-28T09:00:00Z',
            end_date=f'{year}-07-03T17:00:00Z',
        )

        june_response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{year}/6')
        july_response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{year}/7')
        assert june_response.status_code == 200
        assert july_response.status_code == 200

        june_ids = {c['id'] for c in june_response.json()['cards']}
        july_ids = {c['id'] for c in july_response.json()['cards']}
        assert card['id'] in june_ids
        assert card['id'] in july_ids

    def test_archived_and_template_cards_are_excluded(self, api_client, authenticated_session, sample_column):
        year = datetime.now().year
        archived_card = _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-04-05T09:00:00Z',
            end_date=f'{year}-04-05T10:00:00Z',
        )
        archive_response = authenticated_session.patch(f'{api_client}/api/cards/{archived_card["id"]}/archive')
        assert archive_response.status_code == 200

        template_card = _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-04-05T09:00:00Z',
            end_date=f'{year}-04-05T10:00:00Z',
            scheduled=True,
        )

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{year}/4')
        assert response.status_code == 200
        card_ids = {c['id'] for c in response.json()['cards']}
        assert archived_card['id'] not in card_ids
        assert template_card['id'] not in card_ids

    def test_invalid_month_returns_400(self, api_client, authenticated_session, sample_column):
        response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/2026/13')
        assert response.status_code == 400

    def test_card_includes_column_id(self, api_client, authenticated_session, sample_column):
        """The planner's "show columns" display relies on each card carrying
        its column_id so the frontend can resolve it to a column name."""
        year = datetime.now().year
        card = _create_card(
            api_client, authenticated_session, sample_column['id'],
            start_date=f'{year}-05-05T09:00:00Z',
            end_date=f'{year}-05-05T10:00:00Z',
        )

        response = authenticated_session.get(f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{year}/5')
        assert response.status_code == 200
        returned_card = next(c for c in response.json()['cards'] if c['id'] == card['id'])
        assert returned_card['column_id'] == sample_column['id']


@pytest.mark.api
class TestPlannerScheduledOccurrenceProjection:
    def test_template_without_duration_defaults_to_one_hour(self, api_client, authenticated_session, sample_column):
        """A schedule whose template card has no start/end date should project
        1-hour-long virtual occurrences (DEFAULT_OCCURRENCE_DURATION)."""
        template = _create_card(api_client, authenticated_session, sample_column['id'], title='Daily template')

        tomorrow = datetime.now() + timedelta(days=1)
        schedule_response = authenticated_session.post(f'{api_client}/api/schedules', json={
            'card_id': template['id'],
            'keep_source_card': True,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow.strftime('%Y-%m-%dT%H:%M:%S'),
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
        })
        assert schedule_response.status_code == 201, schedule_response.text

        response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{tomorrow.year}/{tomorrow.month}'
            f'?include_scheduled=true'
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data['virtual']) >= 1

        occurrence = data['virtual'][0]
        start = datetime.fromisoformat(occurrence['start_date'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(occurrence['end_date'].replace('Z', '+00:00'))
        assert end - start == timedelta(hours=1)

    def test_include_scheduled_false_omits_virtual_occurrences(self, api_client, authenticated_session, sample_column):
        template = _create_card(api_client, authenticated_session, sample_column['id'], title='Daily template')
        tomorrow = datetime.now() + timedelta(days=1)
        authenticated_session.post(f'{api_client}/api/schedules', json={
            'card_id': template['id'],
            'keep_source_card': True,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': tomorrow.strftime('%Y-%m-%dT%H:%M:%S'),
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
        })

        response = authenticated_session.get(
            f'{api_client}/api/boards/{sample_column["board_id"]}/planner/month/{tomorrow.year}/{tomorrow.month}'
        )
        assert response.status_code == 200
        assert response.json()['virtual'] == []


@pytest.mark.api
class TestPlannerPermissions:
    def test_board_viewer_can_access_planner_endpoints(self, api_client, authenticated_session, second_user_session, sample_board, sample_column):
        second_user = get_current_user(api_client, second_user_session)
        grant_response = authenticated_session.post(
            f'{api_client}/api/users/{second_user["id"]}/roles',
            json={'role_name': 'board_viewer', 'board_id': sample_board['id']}
        )
        assert grant_response.status_code == 200

        year = datetime.now().year
        response = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/planner/year/{year}')
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_user_without_board_access_is_forbidden(self, api_client, second_user_session, sample_board):
        year = datetime.now().year
        response = second_user_session.get(f'{api_client}/api/boards/{sample_board["id"]}/planner/year/{year}')
        assert response.status_code == 403
