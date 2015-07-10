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

import copy
import numpy
import os
import pandas
import random

from collections import Counter
from fluent.utils.plotting import PlotNLP

try:
  import simplejson as json
except ImportError:
  import json



## TODO: confusion matrices
class ClassificationModel(object):
  """
  Base class for NLP models of classification tasks. When inheriting from this
  class please take note of which methods MUST be overridden, as documented
  below. The Model superclass mainly implements evaluation methods.

  Methods/properties that must be implemented by subclasses:
    - encodePattern(); note the specified format in the docstring below.
    - resetModel()
    - trainModel()
    - testModel()
  """

  def __init__(self, n=16384, w=328, verbosity=1, plot=True, multiclass=False):
    """The SDR dimensions are standard for Cortical.io fingerprints."""
    self.n = n
    self.w = w
    self.multiclass = multiclass
    self.verbosity = verbosity
    self.plot = plot


  def encodeRandomly(self, sample):
    """Return a random bitmap representation of the sample."""
    random.seed(sample)
    return numpy.sort(random.sample(xrange(self.n), self.w))


  def logEncodings(self, patterns, path):
    """Log the encoding dictionaries to a txt file."""
    if not os.path.isdir(path):
      raise ValueError("Invalid path to write file.")

    # Cast numpy arrays to list objects for serialization.
    jsonPatterns = copy.deepcopy(patterns)
    for jp in jsonPatterns:
      jp["pattern"]["bitmap"] = jp["pattern"].get("bitmap", None).tolist()
      jp["labels"] = jp.get("labels", None).tolist()

    with open(os.path.join(path, "encoding_log.txt"), "w") as f:
      f.write(json.dumps(jsonPatterns, indent=1))


  def classifyRandomly(self, labels):
    """Return accuracy of random classifications for the labels."""
    randomLabels = numpy.random.randint(0, labels.max(), labels.shape)
    return (randomLabels == labels).sum() / float(labels.shape[0])


  def _densifyPattern(self, bitmap):
    """Return a numpy array of 0s and 1s to represent the input bitmap."""
    densePattern = numpy.zeros(self.n)
    for i in bitmap:
      densePattern[i] = 1.0
    return densePattern


  @staticmethod
  def getWinningLabels(labelFreq, numLabels=3):
    """
    Returns indices of input array, sorted for highest to lowest value. E.g.
      >>> labelFreq = array([ 0., 4., 0., 1.])
      >>> winners = getWinningLabels(labelFreq, numLabels=3)
      >>> print winners
      array([1, 3])
    Note indices of nonzero values are not included in the returned array.

    @param labelFreq    (numpy.array)   Ints that (in this context) represent
                                        the frequency of inferred labels.
    @param numLabels    (int)           Return this number of most frequent
                                        labels within top k
    @return             (numpy.array)   Indicates largest elements in labelFreq,
                                        sorted greatest to least. Length is up
                                        to numLabels.
    """
    # Note: numpy.argsort favors items later in the array, so for ties, later
    # items are selected first.
    winners = labelFreq.argsort()[::-1][:numLabels]

    return numpy.array([i for i in winners if labelFreq[i] > 0])


  def calculateClassificationResults(self, classifications):  ## TODO: plot
    """Calculate the classification accuracy for each category.
    @param classifications  (list)            Two lists: (0) predictions and (1)
                                              actual classifications. Items in
                                              the predictions list are lists of
                                              ints or None, and items in actual
                                              classifications list are ints.
    @return                 (list)            tuples of class name and accuracy
                                              for that class
    """
    labels = set(classifications[1])
    return [(l, self.calculateAccuracy(classifications, l)) for l in labels]


  def evaluateResults(self, classifications, references, idx):
    """
    Calculate statistics for the predicted classifications against the actual.

    @param classifications  (tuple)     Two lists: (0) predictions and
        (1) actual classifications. Items in the predictions list are numpy
        arrays of ints or [None], and items in actual classifications list
        are numpy arrays of ints.

    @param references       (list)            Classification label strings.

    @param idx              (list)            Indices of test samples.

    @return                 (tuple)           Returns a 2-item tuple w/ the
        accuracy (float) and confusion matrix (numpy array).
    """
    if self.verbosity > 0:
      self.printTrialReport(classifications, references, idx)

    accuracy = self.calculateAccuracy(classifications)
    # cm = self.calculateConfusionMatrix(classifications, references)
    cm = numpy.array([])

    return (accuracy, cm)


  def evaluateCumulativeResults(self, intermResults):
    """
    Cumulative statistics for the outputs of evaluateTrialResults().

    @param intermResults      (list)          List of returned results from
                                              evaluateTrialResults().
    @return                   (dict)          Returns a dictionary with entries
                                              for max, mean, and min accuracies,
                                              and the mean confusion matrix.
    """
    accuracy = []
    cm = numpy.zeros((intermResults[0][1].shape))

    # Find mean, max, and min values for the metrics.
    for result in intermResults:
      accuracy.append(result[0])
      cm = numpy.add(cm, result[1])

    results = {"max_accuracy":max(accuracy),
               "mean_accuracy":sum(accuracy)/float(len(accuracy)),
               "min_accuracy":min(accuracy),
               "total_cm":cm}

    if self.verbosity > 0:
      self.printCumulativeReport(results)

    if self.plot and self.multiclass:
      self.plotConfusionMatrix(cm)

    return results


  @staticmethod
  def calculateAccuracy(classifications):
    """
    @param classifications    (tuple)     First element is list of predicted
        labels, second is list of actuals; items are numpy arrays.

    @return                   (float)     Correct labels out of total labels,
        where a label is correct if it is amongst the actuals.
    """
    if len(classifications[0]) != len(classifications[1]):
      raise ValueError("Classification lists must have same length.")

    accuracy = 0.0
    for actual, predicted in zip(classifications[1], classifications[0]):
      commonElems = numpy.intersect1d(actual, predicted)
      accuracy += len(commonElems)/float(len(actual))

    return accuracy/len(classifications[1])


  # TODO: Figure out better way to report multilabel outputs--only handles
  # single label now
  @staticmethod
  def calculateConfusionMatrix(classifications, references):
    """Returns confusion matrix as a pandas dataframe."""
    if len(classifications[0]) != len(classifications[1]):
      raise ValueError("Classification lists must have same length.")

    total = len(references)
    cm = numpy.zeros((total, total+1))
    for actual, predicted in zip(classifications[1], classifications[0]):
      if predicted is not None:
        cm[actual[0]][predicted[0]] += 1
      else:
        # No predicted label, so increment the "(none)" column.
        cm[actual[0]][total] += 1
    cm = numpy.vstack((cm, numpy.sum(cm, axis=0)))
    cm = numpy.hstack((cm, numpy.sum(cm, axis=1).reshape(total+1,1)))

    cm = pandas.DataFrame(
      data=cm,
      columns=references+["(none)"]+["Actual Totals"],
      index=references+["Prediction Totals"])

    return cm


  @staticmethod
  def printTrialReport(labels, refs, idx):
    """Print columns for sample #, actual label, and predicted label."""
    template = "{0:<10}|{1:<55}|{2:<55}"
    print "Evaluation results for the trial:"
    print template.format("#", "Actual", "Predicted")
    for i in xrange(len(labels[0])):
      if not any(labels[0][i]):
        # No predicted classes for this sample.
        print template.format(idx[i],
                              [refs[label] for label in labels[1][i]],
                              "(none)")
      else:
        print template.format(idx[i],
                              [refs[label] for label in labels[1][i]],
                              [refs[label] for label in labels[0][i]])


  ## TODO: pprint
  @staticmethod
  def printCumulativeReport(results):
    """
    Prints results as returned by evaluateFinalResults() after several trials.
    """
    print "---------- RESULTS ----------"
    print "max, mean, min accuracies = "
    print "{0:.3f}, {1:.3f}, {2:.3f}".format(
    results["max_accuracy"], results["mean_accuracy"], results["min_accuracy"])
    print "total confusion matrix =\n", results["total_cm"]


  @staticmethod
  def printFinalReport(trainSize, accuracies):
    """Prints result accuracies."""
    template = "{0:<20}|{1:<10}"
    print "Evaluation results for this experiment:"
    print template.format("Size of training set", "Accuracy")
    for i, a in enumerate(accuracies):
      print template.format(trainSize[i], a)


  @staticmethod
  def plotConfusionMatrix(cm):
    """Output plotly confusion matrix."""
    PlotNLP().confusionMatrix(cm)


  def encodePattern(self, pattern):
    """
    The subclass implementations must return the encoding in the following
    format:
      {
        ["text"]:sample,
        ["sparsity"]:sparsity,
        ["bitmap"]:bitmapSDR
      }
    Note: sample is a string, sparsity is float, and bitmapSDR is a numpy array.
    """
    raise NotImplementedError


  def resetModel(self):
    raise NotImplementedError


  def trainModel(self, sample, labels):
    raise NotImplementedError


  def testModel(self, sample, numLabels):
    raise NotImplementedError
