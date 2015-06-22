# ----------------------------------------------------------------------
# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2015, Numenta, Inc.  Unless you have purchased from
# Numenta, Inc. a separate commercial license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

import numpy
import os

from fluent.models.classification_model import ClassificationModel
from fluent.encoders.cio_encoder import CioEncoder

from cortipy.cortical_client import CorticalClient



class ClassificationModelEndpoint(ClassificationModel):
  """
  Class to run the survey response classification task with Cortical.io
  text endpoint encodings and classification system.

  From the experiment runner, the methods expect to be fed one sample at a time.
  """

  def __init__(self, verbosity=1):
    """
    Initialize the CorticalClient and CioEncoder. Requires a valid API key
    """
    super(ClassificationModelEndpoint, self).__init__(verbosity)

    self.encoder = CioEncoder(cacheDir="./experiments/cache")
    self.client = CorticalClient(self.encoder.apiKey)

    self.n = self.encoder.n
    self.w = int((self.encoder.targetSparsity/100) * self.n)

    self.positives = {}
    self.categoryBitmaps = {}


  def encodePattern(self, pattern):
    """
    Encode an SDR of the input string by querying the Cortical.io API.

    @param pattern     (list)           Tokenized sample, where each item is a string
    @return           (dictionary)      Dictionary, containing text, sparsity, and bitmap
    Example return dict:
    {
      "text": "Example text",
      "sparsity": 0.03,
      "bitmap": numpy.array()
    }
    """
    text = " ".join(pattern)
    fpInfo = self.encoder.encode(text)
    if self.verbosity > 1:
      print "Fingerprint sparsity = {0}%.".format(fpInfo["sparsity"])

    if fpInfo:
      text = fpInfo["text"] if "text" in fpInfo else fpInfo["term"]
      bitmap = numpy.array(fpInfo["fingerprint"]["positions"])
      sparsity = fpInfo["sparsity"]
    else:
      bitmap = self.encodeRandomly(text)
      sparsity = float(self.w) / self.n

    return {"text": text, "sparsity": sparsity, "bitmap": bitmap}


  def resetModel(self):
    """Reset the model"""
    self.positives.clear()
    self.categoryBitmaps.clear()


  def trainModel(self, sample, label, negatives=None):
    """
    Train the classifier on the input sample and label. Use Cortical.io's
    createClassification to make a bitmap that represents the class

    @param sample     (dictionary)      Dictionary, containing text, sparsity, and bitmap
    @param label      (int)             Reference index for the classification
                                        of this sample.
    @param negatives  (list)            Each item is the text for the negative samples
    """
    if label not in self.positives:
      self.positives[label] = []
    self.positives[label].append(sample["text"])

    self.categoryBitmaps[label] = self.client.createClassification(str(label),
        self.positives[label])["positions"]


  def testModel(self, sample):
    """
    Test the Cortical.io classifier on the input sample. Returns a dictionary
    containing various distance metrics between the sample and the classes.

    @param sample     (dictionary)      Dictionary, containing text, sparsity, and bitmap
    @return           (dictionary)      The distances between the sample and the classes
    Example return dict:
      {
        0: {
          "cosineSimilarity": 0.6666666666666666,
          "euclideanDistance": 0.3333333333333333,
          "jaccardDistance": 0.5,
          "overlappingAll": 6,
          "overlappingLeftRight": 0.6666666666666666,
          "overlappingRightLeft": 0.6666666666666666,
          "sizeLeft": 9,
          "sizeRight": 9,
          "weightedScoring": 0.4436476984102028
        }
      }
    """

    sampleBitmap = sample["bitmap"].tolist()

    distances = {}
    for cat, catBitmap in self.categoryBitmaps.iteritems():
      distances[cat] = self.client.compare(sampleBitmap, catBitmap)

    return distances
