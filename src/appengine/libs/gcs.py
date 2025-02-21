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
"""App Engine GCS helpers."""

from builtins import object
from future import standard_library
standard_library.install_aliases()
import base64
import collections
import datetime
import json
import time
import urllib.parse

import googleapiclient

from base import utils
from google_cloud_utils import blobs
from google_cloud_utils import storage
from system import environment

STORAGE_URL = 'https://storage.googleapis.com/%s'
DEFAULT_URL_VALID_SECONDS = 30 * 60  # 30 minutes.
MAX_UPLOAD_SIZE = 15 * 1024 * 1024 * 1024  # 15 GB.

GcsUpload = collections.namedtuple(
    'GcsUpload',
    ['url', 'bucket', 'key', 'google_access_id', 'policy', 'signature'])


class GcsError(Exception):
  """Base class for exceptions in this module."""


def sign_data(data):
  """Sign data with the default App Engine service account."""
  iam = googleapiclient.discovery.build('iamcredentials', 'v1')
  service_account = 'projects/-/serviceAccounts/' + utils.service_account_email(
  )

  response = iam.projects().serviceAccounts().signBlob(
      name=service_account,
      body={
          'delegates': [],
          'payload': base64.b64encode(data),
      }).execute()

  try:
    return base64.b64decode(response['signedBlob'])
  except Exception as e:
    raise GcsError('Invalid response: ' + str(e))


class SignedGcsHandler(object):
  """Handler for signing and redirecting to a GCS object."""

  def serve_gcs_object(self, bucket, object_path, content_disposition=None):
    """Serve a GCS object."""
    url = get_signed_url(bucket, object_path)

    if content_disposition:
      content_disposition_params = {
          'response-content-disposition': content_disposition,
      }

      url += '&' + urllib.parse.urlencode(content_disposition_params)

    self.redirect(url)


def _get_expiration_time(expiry_seconds):
  """Return a timestamp |expiry_seconds| from now."""
  return int(time.time() + expiry_seconds)


def get_signed_url(bucket_name,
                   path,
                   method='GET',
                   expiry=DEFAULT_URL_VALID_SECONDS):
  """Return a signed url."""
  timestamp = _get_expiration_time(expiry)
  blob = '%s\n\n\n%d\n/%s/%s' % (method, timestamp, bucket_name, path)

  local_server = environment.get_value('LOCAL_GCS_SERVER_HOST')
  if local_server:
    url = local_server + '/' + bucket_name
    signed_blob = 'SIGNATURE'
    service_account_name = 'service_account'
  else:
    url = STORAGE_URL % bucket_name
    signed_blob = sign_data(str(blob))
    service_account_name = utils.service_account_email()

  params = {
      'GoogleAccessId': service_account_name,
      'Expires': timestamp,
      'Signature': base64.b64encode(signed_blob),
  }

  return str(url + '/' + path + '?' + urllib.parse.urlencode(params))


def prepare_upload(bucket_name, path, expiry=DEFAULT_URL_VALID_SECONDS):
  """Prepare a signed GCS upload."""
  expiration_time = (
      datetime.datetime.utcnow() + datetime.timedelta(seconds=expiry))

  conditions = [
      {
          'key': path
      },
      {
          'bucket': bucket_name
      },
      ['content-length-range', 0, MAX_UPLOAD_SIZE],
      ['starts-with', '$x-goog-meta-filename', ''],
  ]

  policy = base64.b64encode(
      json.dumps({
          'expiration': expiration_time.isoformat() + 'Z',
          'conditions': conditions,
      }))

  local_server = environment.get_value('LOCAL_GCS_SERVER_HOST')
  if local_server:
    url = local_server
    signature = 'SIGNATURE'
    service_account_name = 'service_account'
  else:
    url = STORAGE_URL % bucket_name
    signature = base64.b64encode(sign_data(policy))
    service_account_name = utils.service_account_email()

  return GcsUpload(url, bucket_name, path, service_account_name, policy,
                   signature)


def prepare_blob_upload():
  """Prepare a signed GCS blob upload."""
  return prepare_upload(storage.blobs_bucket(), blobs.generate_new_blob_name())
