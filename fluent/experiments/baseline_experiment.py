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
python experiments/baseline_experiment.py data/sample_reviews/sample_reviews_data_training.csv
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


def runExperiment(model, patterns, labels, idxSplits):
  """
  @param model          (Model)               Classification model instance.
  @param patterns       (list)                Each item is a dict with the
                                              sample encoding a numpy array
                                              bitmap in field "bitmap".
  @param labels         (numpy.array)         Ints specifying classifications.
  @param idxSplits      (tuple)               Tuple of train/eval split data
                                              indices. idxSplits[0] is `train`.
                                              idxSplits[1] is `eval`.
  @return                                     Return same as testing().
  """
  model.resetModel()
  training(model, [(patterns[i][0], labels[i]) for i in idxSplits[0]])
  evalSet = []
  for idx in idxSplits[1]:
    evalSet.append((patterns[idx][0], patterns[idx][1]))
  return testing(model, evalSet)


# training() and testing() methods send one data sample at a time to the model,
# i.e. streaming input.
def training(model, trainSet):
  """Trains model on the bitmap patterns and corresponding labels lists."""
  count = 0
  for x in trainSet:
    if count%100 == 0:
      print "Trained %d examples" %(count)
    model.trainModel(x[0], x[1])
    count += 1


def testing(model, evalSet):
  """
  Tests model on the bitmap patterns and corresponding labels lists.

  @return trialResults    (list)            List of two lists, where the first
                                            list is the model's predicted
                                            classifications, and the second list
                                            is the actual classifications.
  """
  trialResults = [[], []]
  count = 0
  for x in evalSet:
    # Take sample, # of labels as params and return predicted distribution over
    # labels
    if count%100 == 0:
      print "Tested %d examples" %(count)
    predicted = model.testModel(x[0], numLabels=len(x[1]))
    trialResults[0].append(predicted)
    trialResults[1].append(x[1])
    count += 1
  return trialResults


def calculateResults(model, results, refs, indices, fileName, samples):
  """
  Evaluate the results, returning accuracy and confusion matrix, and writing
  the confusion matrix to a CSV.
  """
  result = model.evaluateResults(results, refs, indices, samples)
  result[1].to_csv(fileName)
  return result


def computeExpectedAccuracy(predictedLabels, dataPath):
  """
  Compute the accuracy of the models predictions against what we expect it to
  predict; considers only single classification.
  """
  _, expectedLabels = readCSV(dataPath, 2, [3])
  if len(expectedLabels) != len(predictedLabels):
    raise ValueError("Lists of labels must have the same length.")

  accuracy = len([i for i in xrange(len(expectedLabels))
    if expectedLabels[i]==predictedLabels[i]]) / float(len(expectedLabels))

  print "Accuracy against expected classifications = ", accuracy


def setupData(args, texter, dataPath):
  """ Performs data preprocessing and setup given the user-specified args.

  @param args       (Namespace)             User-provided arguments via the
                                            command line
  @param texter     (TextPreprocess)        Text preprocessing object
  @param dataPath   (str)                   Path where data is located
  @return            (tuple)                Tuple where first entry is a list
                                            of the samples, the second is the
                                            list of gold labels per example,
                                            the third is the list of all
                                            possible labels, and the fourth is
                                            the labels per example in the data.
  """
  if args.useMultiClass:
    rawSamples, labels = readCSV(dataPath, 2, range(3,6))
  else:
    rawSamples, labels = readCSV(dataPath, 2, [3])

  labelReference = list(set(labels))
  labels = numpy.array([labelReference.index(l) for l in labels], dtype="int8")

  # Responsible for generating a list of list of labels for the
  # gold standard labels
  sampleLabelMapping = collections.defaultdict(list)
  for idx, s in enumerate(rawSamples):
    sampleLabelMapping[s].append(int(labels[idx]))

  # Ensure each sample also has count of number of labels assigned
  if args.textPreprocess:
    samples = []
    for sample in rawSamples:
      samples.append((texter.tokenize(sample,
                             ignoreCommon=100,
                             removeStrings=["[identifier deleted]"],
                             correctSpell=True),
                                sampleLabelMapping[sample]))
  else:
    samples = []
    for sample in rawSamples:
      samples.append((texter.tokenize(sample),
                      sampleLabelMapping[sample]))

  return (samples, labelReference, labels)

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
  modelPath = os.path.abspath(
    os.path.join(root, args.resultsDir, args.expName, args.modelName))
  if not os.path.exists(modelPath):
    os.makedirs(modelPath)

  # Verify input params.
  if not os.path.isfile(dataPath):
    raise ValueError("Invalid data path.")
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
                         multiclass=args.useMultiClass)
    except ImportError:
      raise RuntimeError("Could not find model class \'%s\' to import."
                         % args.modelName)

  print "Reading in data and preprocessing."
  preprocessTime = time.time()
  texter = TextPreprocess()

  (samples, labelReference, labels) = setupData(args, texter, dataPath)

  print("Preprocessing complete; elapsed time is {0:.2f} seconds.".
        format(time.time() - preprocessTime))
  if args.verbosity > 1:
    for i, s in enumerate(samples): print i, s, labelReference[labels[i]]

  print "Encoding the data."
  encodeTime = time.time()
  patterns = [(model.encodePattern(s[0]), s[1]) for s in samples]

  print("Done encoding; elapsed time is {0:.2f} seconds.".
        format(time.time() - encodeTime))
  model.logEncodings(patterns, modelPath)

  # Either we train on all the data, test on all the data, or run k-fold CV.
  if args.train:
    training(model, [(p[0], labels[i]) for i, p in enumerate(patterns)])

  errors = [] # To store the indices of the errors made by the classifier
  if args.test:
    evalSet = []
    for idx, p in enumerate(patterns):
      evalSet.append((p[0], p[1]))
    results = testing(model, evalSet)
    resultMetrics = calculateResults(
      model, results, labelReference, xrange(len(samples)),
      os.path.join(modelPath, "test_results.csv"), samples)
    print resultMetrics
    if model.plot:
      model.plotConfusionMatrix(resultMetrics[1])

  elif args.kFolds>1:
    # Run k-folds cross validation -- train the model on a subset, and evaluate
    # on the remaining subset.
    partitions = KFolds(args.kFolds).split(range(len(samples)), randomize=True)
    intermResults = []
    predictions = []
    for k in xrange(args.kFolds):
      print "Training and testing for CV fold {0}.".format(k)
      kTime = time.time()
      trialResults = runExperiment(model, patterns, labels, partitions[k])
      print("Fold complete; elapsed time is {0:.2f} seconds.".format(
            time.time() - kTime))

      if args.expectationDataPath:
        # Keep the predicted labels (top prediction only) for later.
        p = [l if l else [None] for l in trialResults[0]]
        predictions.append(
          [labelReference[idx[0]] if idx[0] != None else '(none)' for idx in p])

      print "Calculating intermediate results for this fold. Writing to CSV."
      intermResults.append(calculateResults(
        model, trialResults, labelReference, partitions[k][1],
        os.path.join(modelPath, "evaluation_fold_" + str(k) + ".csv"), samples))

    print "Calculating cumulative results for {0} trials.".format(args.kFolds)
    results = model.evaluateCumulativeResults(intermResults) #
    results["total_cm"].to_csv(os.path.join(modelPath, "evaluation_totals.csv"))
    if args.expectationDataPath:
      computeExpectedAccuracy(list(itertools.chain.from_iterable(predictions)),
        os.path.abspath(os.path.join(root, '../..', args.expectationDataPath)))

  print "Calculating random classifier results for comparison."
  print model.classifyRandomly(labels)

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
  parser.add_argument("--useMultiClass",
                      type=bool,
                      help="Whether to use multiple classes per sample",
                      default=False)
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
