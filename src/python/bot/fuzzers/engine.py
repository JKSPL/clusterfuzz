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
"""Fuzzing engine interface."""

from builtins import object
from collections import namedtuple
import random

from system import environment

_ENGINES = {}
_TRIAL_PROBABILITY_FUZZ = 0.2
_TRIAL_PROBABILITY_OTHERS = 0.05


class FuzzOptions(object):
  """Represents options passed to the engine. Can be overridden to provide more
  options."""

  def __init__(self, corpus_dir, arguments, strategies):
    self.corpus_dir = corpus_dir
    self.arguments = arguments
    self.strategies = strategies


class Crash(object):
  """Represents a crash found by the fuzzing engine."""

  def __init__(self, input_path, stacktrace, reproduce_args, crash_time):
    self.input_path = input_path
    self.stacktrace = stacktrace
    self.reproduce_args = reproduce_args
    self.crash_time = crash_time


class FuzzResult(object):
  """Represents a result of a fuzzing session: a list of crashes found and the
  stats generated."""

  def __init__(self, logs, command, crashes, stats, time_executed):
    self.logs = logs
    self.command = command
    self.crashes = crashes
    self.stats = stats
    self.time_executed = time_executed


# Results from running a testcase against a target.
ReproduceResult = namedtuple(
    'ReproduceResult', ['command', 'return_code', 'time_executed', 'output'])


class Engine(object):
  """Base interface for a grey box fuzzing engine."""

  @property
  def name(self):
    """Get the name of the engine."""
    raise NotImplementedError

  def prepare(self, corpus_dir, target_path, build_dir):
    """Prepare for a fuzzing session, by generating options. Returns a
    FuzzOptions object.

    Args:
      corpus_dir: The main corpus directory.
      target_path: Path to the target.
      build_dir: Path to the build directory.

    Returns:
      A FuzzOptions object.
    """
    raise NotImplementedError

  def fuzz(self, target_path, options, reproducers_dir, max_time):
    """Run a fuzz session.

    Args:
      target_path: Path to the target.
      options: The FuzzOptions object returned by prepare().
      reproducers_dir: The directory to put reproducers in when crashes
          are found.
      max_time: Maximum allowed time for the fuzzing to run.

    Returns:
      A FuzzResult object.
    """
    raise NotImplementedError

  def reproduce(self, target_path, input_path, arguments, max_time):
    """Reproduce a crash given an input.

    Args:
      target_path: Path to the target.
      input_path: Path to the reproducer input.
      arguments: Additional arguments needed for reproduction.
      max_time: Maximum allowed time for the reproduction.

    Returns:
      A ReproduceResult.
    """
    raise NotImplementedError

  def minimize_corpus(self, target_path, arguments, input_dirs, output_dir,
                      reproducers_dir, max_time):
    """Optional (but recommended): run corpus minimization.

    Args:
      target_path: Path to the target.
      arguments: Additional arguments needed for corpus minimization.
      input_dirs: Input corpora.
      output_dir: Output directory to place minimized corpus.
      reproducers_dir: The directory to put reproducers in when crashes are
          found.
      max_time: Maximum allowed time for the minimization.

    Returns:
      A FuzzResult object.
    """
    raise NotImplementedError

  def minimize_testcase(self, target_path, arguments, input_path, output_path,
                        max_time):
    """Optional (but recommended): Minimize a testcase.

    Args:
      target_path: Path to the target.
      arguments: Additional arguments needed for testcase minimization.
      input_path: Path to the reproducer input.
      output_path: Path to the minimized output.
      max_time: Maximum allowed time for the minimization.

    Returns:
      A ReproduceResult.
    """
    raise NotImplementedError

  def cleanse(self, target_path, arguments, input_path, output_path, max_time):
    """Optional (but recommended): Cleanse a testcase.

    Args:
      target_path: Path to the target.
      arguments: Additional arguments needed for testcase cleanse.
      input_path: Path to the reproducer input.
      output_path: Path to the cleansed output.
      max_time: Maximum allowed time for the cleanse.

    Returns:
      A ReproduceResult.
    """
    raise NotImplementedError


def register(name, engine_class):
  """Register a fuzzing engine."""
  if name in _ENGINES:
    raise ValueError('Engine {name} is already registered'.format(name=name))

  _ENGINES[name] = engine_class


def get(name):
  """Get an implemntation of a fuzzing engine, or None if one does not exist."""
  engine_class = _ENGINES.get(name)
  if engine_class:
    return engine_class()

  return None


def do_trial():
  """Returns or not we should trial using this new implementation."""
  use_new_impl = environment.get_value('USE_NEW_ENGINE_IMPL')
  if use_new_impl:
    return True

  if use_new_impl is False:  # Explicitly set to false.
    return False

  if environment.get_value('TASK_NAME') == 'fuzz':
    probability = _TRIAL_PROBABILITY_FUZZ
  else:
    probability = _TRIAL_PROBABILITY_OTHERS

  return random.SystemRandom().random() < probability
