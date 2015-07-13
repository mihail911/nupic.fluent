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
"""
Initial experiment runner for classification survey question responses.

EXAMPLE: from the fluent directory, run...
  python experiments/baseline_experiment.py
  data/sample_reviews/sample_reviews_data_training.csv

  - The runner sets up the data path such that the experiment runs on a single
  data file located in the nupic.fluent/data directory. The data path MUST BE
  SPECIFIED at the cmd line.
  - This example runs the ClassificationModelRandomSDR subclass of Model. To use
  a different model, use cmd line args modelName and modelModuleName.
  - The call to readCSV() below is specific for the format of this data file,
  and should be changed for CSVs with different columns.

Please note the following definitions:
- k-fold cross validation: the training dataset is split
  differently for each of the k trials. The majority of the dataset is used for
  training, and a small portion (1/k) is held out for evaluation; this
  evaluation data is different from the test data.
- classification and label are used interchangeably
"""


import argparse
import collections
import cPickle as pkl
import itertools
import numpy
import os
import time

from fluent.utils.csv_helper import readCSV
from fluent.utils.data_split import KFolds
from fluent.utils.text_preprocess import TextPreprocess


def runExperiment(model, patterns, idxSplits):
  """
  Trains the model on patterns specified by the first entry of idxSplits, then
  tests on the patterns of the second entry on idxSplits.

  @param model          (Model)       Classification model instance.
  @param patterns       (list)        Each item is a dict with the sample
                                      encoding a numpy array bitmap in field
                                      "bitmap".
  @param idxSplits      (tuple)       Tuple of train/eval split data indices.
  @return                             Return same as testing().
  """
  model.resetModel()
  training(model, [patterns[i] for i in idxSplits[0]])
  return testing(model, [patterns[i] for i in idxSplits[1]])


# training() and testing() methods send one data sample at a time to the model,
# i.e. streaming input.
def training(model, trainSet):
  """
  Trains model on the bitmap patterns and corresponding labels lists one at a
  time (i.e. streaming).
  """
  for sample in trainSet:
    model.trainModel(sample["pattern"], sample["labels"])


def testing(model, evalSet):
  """
  Tests model on the bitmap patterns and corresponding labels lists, one at a
  time (i.e. streaming).

  @return trialResults    (list)      List of two lists, where the first list
      is the model's predicted classifications, and the second list is the
      actual classifications.
  """
  trialResults = ([], [])
  for sample in evalSet:
    predicted = model.testModel(sample["pattern"])
    trialResults[0].append(predicted)
    trialResults[1].append(sample["labels"])
  return trialResults


def calculateResults(model, results, refs, indices, fileName):
  """
  Evaluate the results, returning accuracy and confusion matrix, and writing
  the confusion matrix to a CSV.

  TODO: csv writing broken until ClassificationModel confusion matrix is fixed
  """
  result = model.evaluateResults(results, refs, indices)
  # result[1].to_csv(fileName)
  return result


def computeExpectedAccuracy(predictedLabels, expectedDataDict, labelReference,
                            partitions):
  """
  Compute the accuracy of the models predictions against what we expect it to
  predict; considers multiclass classification.
  """

  accuracies = numpy.zeros((len(predictedLabels)))
  for i, predictionList in enumerate(predictedLabels):
    expectedList = expectedDataDict.items()[partitions[i]][1]
    accuracies[i] += (float(len(set(predictionList) & set(expectedList)))
                      / len(expectedList))
  accuracy = numpy.sum(accuracies) / len(predictedLabels)

  return accuracy

def setupData(args, dataPath, expectedDataPath):
  """ Performs data preprocessing and setup given the user-specified args.

  @param args       (Namespace)     User-provided arguments via the cmd line.
  @param dataPath   (str)           Path where data is located.
  @return           (tuple)         Tuple where first entry is a list of the
      samples, the second is the list of gold labels per example, the third is
      the list of all possible labels, and the fourth is the labels per example
      in the data.
  """
  dataDict = readCSV(dataPath, 2, args.numClasses)
  expectedDataDict = readCSV(expectedDataPath, 2, args.numClasses) #TODO:
                                        # Check whether should put index 2

  # Collect each possible label string into a list, where the indices will be
  # their references throughout the experiment.
  labelReference = list(set(
      itertools.chain.from_iterable(dataDict.values())))

  for sample, labels in dataDict.iteritems():
    dataDict[sample] = numpy.array([labelReference.index(label)
                                    for label in labels],
                                    dtype="int8")

  texter = TextPreprocess()
  if args.textPreprocess:
    samples = [(texter.tokenize(sample,
                                ignoreCommon=100,
                                removeStrings=["[identifier deleted]"],
                                correctSpell=True),
               labels) for sample, labels in dataDict.iteritems()]
  else:
    samples = [(texter.tokenize(sample), labels)
               for sample, labels in dataDict.iteritems()]

  return samples, labelReference, expectedDataDict


def run(args):
  """
  The experiment is configured to run on question response data.

  To run k-folds cross validation, arguments must be: kFolds > 1, train = False,
  test = False. To run either training or testing, kFolds = 1.
  """
  start = time.time()

  # Setup directories.
  root = os.path.dirname(__file__)
  dataPath = os.path.abspath(os.path.join(root, '../..', args.dataFile))
  expectedDataPath = os.path.abspath(os.path.join(root, '../..',
                                                  args.expectationDataPath))
  modelPath = os.path.abspath(
    os.path.join(root, args.resultsDir, args.expName, args.modelName))
  if not os.path.exists(modelPath):
    os.makedirs(modelPath)

  # Verify input params.
  if not os.path.isfile(dataPath):
    raise ValueError("Invalid data path.")
  if not os.path.isfile(expectedDataPath):
    raise ValueError("Invalid data path")
  if (not isinstance(args.kFolds, int)) or (args.kFolds < 1):
    raise ValueError("Invalid value for number of cross-validation folds.")
  if (args.train or args.test) and args.kFolds > 1:
    raise ValueError("Experiment runs either k-folds CV or training/testing, "
                     "not both.")

  # Load or init model.
  if args.load:
    with open(
      os.path.join(modelPath, "model.pkl"), "rb") as f:
      model = pkl.load(f)
    print "Model loaded from \'{0}\'.".format(modelPath)
  else:
    try:
      module = __import__(args.modelModuleName, {}, {}, args.modelName)
      modelClass = getattr(module, args.modelName)
      model = modelClass(verbosity=args.verbosity,
                         numClasses=args.numClasses)
    except ImportError:
      raise RuntimeError("Could not find model class \'%s\' to import."
                         % args.modelName)

  print "Reading in data and preprocessing."
  preprocessTime = time.time()

  samples, labelReference, expectedDataDict = setupData(args, dataPath,
                                                        expectedDataPath)

  print("Preprocessing complete; elapsed time is {0:.2f} seconds.".
        format(time.time() - preprocessTime))
  if args.verbosity > 1:
    for i, s in enumerate(samples):
      labels = [labelReference[idx] for idx in s[1]]
      print i, s, labels

  print "Encoding the data."
  encodeTime = time.time()
  patterns = [{"pattern": model.encodePattern(s[0]),
              "labels": s[1]}
              for s in samples]

  print("Done encoding; elapsed time is {0:.2f} seconds.".
        format(time.time() - encodeTime))
  model.logEncodings(patterns, modelPath)

  # Either we train on all the data, test on all the data, or run k-fold CV.
  if args.train:
    training(model, patterns)

  if args.test:
    results = testing(model, patterns)
    resultMetrics = calculateResults(
      model, results, labelReference, xrange(len(samples)),
      os.path.join(modelPath, "test_results.csv"))
    print resultMetrics
    if model.plot:
      model.plotConfusionMatrix(resultMetrics[1])

  elif args.kFolds > 1:
    # Run k-folds cross validation -- train the model on a subset, and evaluate
    # on the remaining subset.
    partitions = KFolds(args.kFolds).split(range(len(samples)), randomize=True)
    intermResults = []
    expectedIntermResults = numpy.zeros(args.kFolds)

    for k in xrange(args.kFolds):
      predictions = [] # TODO: Make sure it's ok for this to be here...
      print "Training and testing for CV fold {0}.".format(k)
      kTime = time.time()
      trialResults = runExperiment(model, patterns, partitions[k])
      print("Fold complete; elapsed time is {0:.2f} seconds.".format(
            time.time() - kTime))

      if args.expectationDataPath:
        # Keep the predicted labels (top prediction only) for later.
        p = [l if l.any() else [None] for l in trialResults[0]]
        for labelsList in p:
          labels = [labelReference[idx] if idx != None else '(none)' for idx
                    in labelsList]
          predictions.append(labels)

        avgAccuracy = computeExpectedAccuracy(predictions,
          expectedDataDict, labelReference, partitions[k][1])
        expectedIntermResults[k] = avgAccuracy
      print "Calculating intermediate results for this fold. Writing to CSV."
      intermResults.append(calculateResults(
        model, trialResults, labelReference, partitions[k][1],
        os.path.join(modelPath, "evaluation_fold_" + str(k) + ".csv")))

    print "Calculating cumulative results for {0} trials.".format(args.kFolds)
    results = model.evaluateCumulativeResults(intermResults)

    print "Average accuracy against expected labels across %d folds is %f" \
          %(args.kFolds,
            numpy.sum(expectedIntermResults)/len(expectedIntermResults))

    # TODO: csv writing broken until ClassificationModel confusion matrix is fixed
    # results["total_cm"].to_csv(os.path.join(modelPath, "evaluation_totals.csv"))

  ## TODO:
  # print "Calculating random classifier results for comparison."
  # print model.classifyRandomly(labels)

  print "Saving model to \'{0}\' directory.".format(modelPath)
  with open(
    os.path.join(modelPath, "model.pkl"), "wb") as f:
    pkl.dump(model, f)
  print "Experiment complete in {0:.2f} seconds.".format(time.time() - start)


if __name__ == "__main__":

  parser = argparse.ArgumentParser()
  parser.add_argument("dataFile")
  parser.add_argument("--expectationDataPath",
                      default="",
                      type=str,
                      help="Path from fluent root directory to the file with "
                      " expected labels.")
  parser.add_argument("-k", "--kFolds",
                      default=5,
                      type=int,
                      help="Number of folds for cross validation; k=1 will "
                      "run no cross-validation.")
  parser.add_argument("--expName",
                      default="survey_response_sample",
                      type=str,
                      help="Experiment name.")
  parser.add_argument("--modelName",
                      default="ClassificationModelRandomSDR",
                      type=str,
                      help="Name of model class. Also used for model results "
                      "directory and pickle checkpoint.")
  parser.add_argument("--modelModuleName",
                      default="fluent.models.classify_random_sdr",
                      type=str,
                      help="model module (location of model class).")
  parser.add_argument("--numClasses",
                      help="Specifies the number of classes per sample.",
                      type=int,
                      default=3)
  parser.add_argument("--textPreprocess",
                      type=bool,
                      help="Whether to preprocess text",
                      default=False)
  parser.add_argument("--load",
                      help="Load the serialized model.",
                      default=False)
  parser.add_argument("--train",
                      help="Train the model on all the data.",
                      default=False)
  parser.add_argument("--test",
                      help="Test the model on all the data.",
                      default=False)
  parser.add_argument("--resultsDir",
                      default="results",
                      help="This will hold the evaluation results.")
  parser.add_argument("--verbosity",
                      default=1,
                      type=int,
                      help="verbosity 0 will print out experiment steps, "
                      "verbosity 1 will include results, and verbosity > 1 "
                      "will print out preprocessed tokens and kNN inference "
                      "metrics.")
  args = parser.parse_args()
  run(args)
