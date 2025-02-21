# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""commands tests."""
from future import standard_library
standard_library.install_aliases()
import datetime
import mock
import os
import unittest

from base import errors
from bot.tasks import commands
from datastore import data_types
from datastore import ndb
from tests.test_libs import helpers
from tests.test_libs import test_utils


@commands.set_task_payload
def dummy(_):
  """A dummy function."""
  return os.environ['TASK_PAYLOAD']


@commands.set_task_payload
def dummy_exception(_):
  """A dummy function."""
  raise Exception(os.environ['TASK_PAYLOAD'])


class SetTaskPayloadTest(unittest.TestCase):
  """Test set_task_payload."""

  def setUp(self):
    helpers.patch_environ(self)

  def test_set(self):
    """Test set."""
    task = mock.Mock()
    task.payload.return_value = 'payload something'
    self.assertEqual('payload something', dummy(task))
    self.assertIsNone(os.getenv('TASK_PAYLOAD'))

  def test_exc(self):
    """Test when exception occurs."""
    task = mock.Mock()
    task.payload.return_value = 'payload something'
    with self.assertRaises(Exception) as cm:
      self.assertEqual('payload something', dummy_exception(task))
    self.assertEqual('payload something', cm.exception.message)
    self.assertEqual({'task_payload': 'payload something'}, cm.exception.extras)
    self.assertIsNone(os.getenv('TASK_PAYLOAD'))


@test_utils.with_cloud_emulators('datastore')
class RunCommandTest(unittest.TestCase):
  """Tests for run_command."""

  def setUp(self):
    helpers.patch_environ(self)
    helpers.patch(self, [
        ('fuzz_execute_task', 'bot.tasks.fuzz_task.execute_task'),
        ('progression_execute_task', 'bot.tasks.progression_task.execute_task'),
        'base.utils.utcnow',
        'datastore.ndb.transaction',
    ])

    os.environ['BOT_NAME'] = 'bot_name'
    os.environ['TASK_LEASE_SECONDS'] = '60'
    os.environ['FAIL_WAIT'] = '60'
    self.mock.utcnow.return_value = test_utils.CURRENT_TIME

    # ndb.transaction seems to cause hangs with testbed when run after another
    # test that uses testbed.
    self.mock.transaction.side_effect = lambda f, **_: f()

  def test_run_command_fuzz(self):
    """Test run_command with a normal command."""
    commands.run_command('fuzz', 'fuzzer', 'job')

    self.assertEqual(1, self.mock.fuzz_execute_task.call_count)
    self.mock.fuzz_execute_task.assert_called_with('fuzzer', 'job')

    # Fuzz task should not create any TaskStatus entities.
    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(0, len(task_status_entities))

  def test_run_command_progression(self):
    """Test run_command with a progression task."""
    commands.run_command('progression', '123', 'job')

    self.assertEqual(1, self.mock.progression_execute_task.call_count)
    self.mock.progression_execute_task.assert_called_with('123', 'job')

    # TaskStatus should indicate success.
    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(1, len(task_status_entities))

    task_status = task_status_entities[0]
    self.assertEqual(
        ndb.Key(data_types.TaskStatus, 'progression 123 job'), task_status.key)

    self.assertDictEqual({
        'bot_name': 'bot_name',
        'status': 'finished',
        'time': test_utils.CURRENT_TIME,
    }, task_status.to_dict())

  def test_run_command_exception(self):
    """Test run_command with an exception."""
    self.mock.progression_execute_task.side_effect = Exception

    with self.assertRaises(Exception):
      commands.run_command('progression', '123', 'job')

    # TaskStatus should indicate failure.
    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(1, len(task_status_entities))

    task_status = task_status_entities[0]
    self.assertDictEqual({
        'bot_name': 'bot_name',
        'status': 'errored out',
        'time': test_utils.CURRENT_TIME,
    }, task_status.to_dict())

  def test_run_command_invalid_testcase(self):
    """Test run_command with an invalid testcase exception."""
    self.mock.progression_execute_task.side_effect = errors.InvalidTestcaseError
    commands.run_command('progression', '123', 'job')

    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(1, len(task_status_entities))

    # TaskStatus should still indicate success.
    task_status = task_status_entities[0]
    self.assertDictEqual({
        'bot_name': 'bot_name',
        'status': 'finished',
        'time': test_utils.CURRENT_TIME,
    }, task_status.to_dict())

  def test_run_command_already_running(self):
    """Test run_command with another instance currently running."""
    data_types.TaskStatus(
        id='progression 123 job',
        bot_name='another_bot',
        time=test_utils.CURRENT_TIME,
        status='started').put()

    with self.assertRaises(commands.AlreadyRunningError):
      commands.run_command('progression', '123', 'job')

    self.assertEqual(0, self.mock.progression_execute_task.call_count)

    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(1, len(task_status_entities))

    task_status = task_status_entities[0]
    self.assertDictEqual({
        'bot_name': 'another_bot',
        'status': 'started',
        'time': test_utils.CURRENT_TIME,
    }, task_status.to_dict())

  def test_run_command_already_running_expired(self):
    """Test run_command with another instance currently running, but its lease
    has expired."""
    data_types.TaskStatus(
        id='progression 123 job',
        bot_name='another_bot',
        time=datetime.datetime(1970, 1, 1),
        status='started').put()

    commands.run_command('progression', '123', 'job')
    self.assertEqual(1, self.mock.progression_execute_task.call_count)

    task_status_entities = list(data_types.TaskStatus.query())
    self.assertEqual(1, len(task_status_entities))

    task_status = task_status_entities[0]
    self.assertDictEqual({
        'bot_name': 'bot_name',
        'status': 'finished',
        'time': test_utils.CURRENT_TIME,
    }, task_status.to_dict())
