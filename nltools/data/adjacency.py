from __future__ import division

'''
This data class is for working with similarity/dissimilarity matrices
'''

__author__ = ["Luke Chang"]
__license__ = "MIT"

import os
import pandas as pd
import numpy as np
import six
from copy import deepcopy
from sklearn.metrics.pairwise import pairwise_distances
from sklearn.manifold import MDS
from sklearn.utils import check_random_state
from scipy.spatial.distance import squareform
from scipy.stats import ttest_1samp
import seaborn as sns
import matplotlib.pyplot as plt
from nltools.stats import (correlation_permutation,
                           one_sample_permutation,
                           two_sample_permutation,
                           summarize_bootstrap,
                           matrix_permutation,
                           jackknife_permutation)
from nltools.stats import regress as regression
from nltools.plotting import (plot_stacked_adjacency,
                              plot_silhouette)
from nltools.utils import (all_same,
                           attempt_to_import,
                           concatenate,
                           _bootstrap_apply_func)
from .design_matrix import Design_Matrix
from joblib import Parallel, delayed

# Optional dependencies
nx = attempt_to_import('networkx', 'nx')

MAX_INT = np.iinfo(np.int32).max


class Adjacency(object):

    '''
    Adjacency is a class to represent Adjacency matrices as a vector rather
    than a 2-dimensional matrix. This makes it easier to perform data
    manipulation and analyses.

    Args:
        data: pandas data instance or list of files
        matrix_type: (str) type of matrix.  Possible values include:
                    ['distance','similarity','directed','distance_flat',
                    'similarity_flat','directed_flat']
        Y: Pandas DataFrame of training labels
        **kwargs: Additional keyword arguments

    '''

    def __init__(self, data=None, Y=None, matrix_type=None, labels=None,
                 **kwargs):
        if matrix_type is not None:
            if matrix_type.lower() not in ['distance', 'similarity', 'directed',
                                           'distance_flat', 'similarity_flat',
                                           'directed_flat']:
                raise ValueError("matrix_type must be [None,'distance', "
                                 "'similarity','directed','distance_flat', "
                                 "'similarity_flat','directed_flat']")

        if data is None:
            self.data = np.array([])
            self.matrix_type = 'empty'
            self.is_single_matrix = np.nan
            self.issymmetric = np.nan
        elif isinstance(data, list):
            if isinstance(data[0], Adjacency):
                tmp = concatenate(data)
                for item in ['data', 'matrix_type', 'Y', 'issymmetric']:
                    setattr(self, item, getattr(tmp, item))
            else:
                d_all = []
                symmetric_all = []
                matrix_type_all = []
                for d in data:
                    data_tmp, issymmetric_tmp, matrix_type_tmp, _ = self._import_single_data(d, matrix_type=matrix_type)
                    d_all.append(data_tmp)
                    symmetric_all.append(issymmetric_tmp)
                    matrix_type_all.append(matrix_type_tmp)
                if not all_same(symmetric_all):
                    raise ValueError('Not all matrices are of the same '
                                     'symmetric type.')
                if not all_same(matrix_type_all):
                    raise ValueError('Not all matrices are of the same matrix '
                                     'type.')
                self.data = np.array(d_all)
                self.issymmetric = symmetric_all[0]
                self.matrix_type = matrix_type_all[0]
            self.is_single_matrix = False
        else:
            self.data, self.issymmetric, self.matrix_type, self.is_single_matrix = self._import_single_data(data, matrix_type=matrix_type)

        if Y is not None:
            if isinstance(Y, six.string_types):
                if os.path.isfile(Y):
                    Y = pd.read_csv(Y, header=None, index_col=None)
            if isinstance(Y, pd.DataFrame):
                if self.data.shape[0] != len(Y):
                    raise ValueError("Y does not match the correct size of "
                                     "data")
                self.Y = Y
            else:
                raise ValueError("Make sure Y is a pandas data frame.")
        else:
            self.Y = pd.DataFrame()

        if labels is not None:
            if not isinstance(labels, (list, np.ndarray)):
                raise ValueError("Make sure labels is a list or numpy array.")
            if self.is_single_matrix:
                if len(labels) != self.square_shape()[0]:
                    raise ValueError('Make sure the length of labels matches the shape of data.')
                self.labels = deepcopy(labels)
            else:
                if len(labels) != len(self):
                    if len(labels) != self.square_shape()[0]:
                        raise ValueError('Make sure length of labels either '
                                         'matches the number of Adjacency '
                                         'matrices or the size of a single '
                                         'matrix.')
                    else:
                        self.labels = list(labels) * len(self)
                else:
                    if np.all(np.array([len(x) for x in labels]) != self.square_shape()[0]):
                        raise ValueError("All lists of labels must be same length as shape of data.")
                    self.labels = deepcopy(labels)
        else:
            self.labels = None

    def __repr__(self):
        return ("%s.%s(shape=%s, square_shape=%s, Y=%s, is_symmetric=%s,"
                "matrix_type=%s)") % (
                    self.__class__.__module__,
                    self.__class__.__name__,
                    self.shape(),
                    self.square_shape(),
                    len(self.Y),
                    self.issymmetric,
                    self.matrix_type)

    def __getitem__(self, index):
        new = self.copy()
        if isinstance(index, int):
            new.data = np.array(self.data[index, :]).flatten()
            new.is_single_matrix = True
        else:
            new.data = np.array(self.data[index, :])
        if not self.Y.empty:
            new.Y = self.Y.iloc[index]
        return new

    def __len__(self):
        if self.is_single_matrix:
            return 1
        else:
            return self.data.shape[0]

    def __iter__(self):
        for x in range(len(self)):
            yield self[x]

    def __add__(self, y):
        new = deepcopy(self)
        if isinstance(y, (int, float)):
            new.data = new.data + y
        if isinstance(y, Adjacency):
            if self.shape() != y.shape():
                raise ValueError('Both Adjacency() instances need to be the '
                                 'same shape.')
            new.data = new.data + y.data
        return new

    def __sub__(self, y):
        new = deepcopy(self)
        if isinstance(y, (int, float)):
            new.data = new.data - y
        if isinstance(y, Adjacency):
            if self.shape() != y.shape():
                raise ValueError('Both Adjacency() instances need to be the '
                                 'same shape.')
            new.data = new.data - y.data
        return new

    def __mul__(self, y):
        new = deepcopy(self)
        if isinstance(y, (int, float)):
            new.data = new.data * y
        if isinstance(y, Adjacency):
            if self.shape() != y.shape():
                raise ValueError('Both Adjacency() instances need to be the '
                                 'same shape.')
            new.data = np.multiply(new.data, y.data)
        return new

    def _import_single_data(self, data, matrix_type=None):
        ''' Helper function to import single data matrix.'''

        if isinstance(data, six.string_types):
            if os.path.isfile(data):
                data = pd.read_csv(data)
            else:
                raise ValueError('Make sure you have specified a valid file '
                                 'path.')

        def test_is_single_matrix(data):
            if len(data.shape) == 1:
                return True
            else:
                return False

        if matrix_type is not None:
            if matrix_type.lower() == 'distance_flat':
                matrix_type = 'distance'
                data = np.array(data)
                issymmetric = True
                is_single_matrix = test_is_single_matrix(data)
            elif matrix_type.lower() == 'similarity_flat':
                matrix_type = 'similarity'
                data = np.array(data)
                issymmetric = True
                is_single_matrix = test_is_single_matrix(data)
            elif matrix_type.lower() == 'directed_flat':
                matrix_type = 'directed'
                data = np.array(data).flatten()
                issymmetric = False
                is_single_matrix = test_is_single_matrix(data)
            elif matrix_type.lower() in ['distance', 'similarity', 'directed']:
                if data.shape[0] != data.shape[1]:
                    raise ValueError('Data matrix must be square')
                data = np.array(data)
                matrix_type = matrix_type.lower()
                if matrix_type in ['distance', 'similarity']:
                    issymmetric = True
                    data = data[np.triu_indices(data.shape[0], k=1)]
                else:
                    issymmetric = False
                    if isinstance(data, pd.DataFrame):
                        data = data.values.flatten()
                    elif isinstance(data, np.ndarray):
                        data = data.flatten()
                is_single_matrix = True
        else:
            if len(data.shape) == 1:  # Single Vector
                try:
                    data = squareform(data)
                except ValueError:
                    print('Data is not flattened upper triangle from '
                          'similarity/distance matrix or flattened directed '
                          'matrix.')
                is_single_matrix = True
            elif data.shape[0] == data.shape[1]:  # Square Matrix
                is_single_matrix = True
            else:  # Rectangular Matrix
                data_all = deepcopy(data)
                try:
                    data = squareform(data_all[0, :])
                except ValueError:
                    print('Data is not flattened upper triangle from multiple '
                          'similarity/distance matrices or flattened directed '
                          'matrices.')
                is_single_matrix = False

            # Test if matrix is symmetrical
            if np.all(data[np.triu_indices(data.shape[0], k=1)] == data.T[np.triu_indices(data.shape[0], k=1)]):
                issymmetric = True
            else:
                issymmetric = False

            # Determine matrix type
            if issymmetric:
                if np.sum(np.diag(data)) == 0:
                    matrix_type = 'distance'
                elif np.sum(np.diag(data)) == data.shape[0]:
                    matrix_type = 'similarity'
                data = data[np.triu_indices(data.shape[0], k=1)]
            else:
                matrix_type = 'directed'
                data = data.flatten()

            if not is_single_matrix:
                data = data_all

        return (data, issymmetric, matrix_type, is_single_matrix)

    def isempty(self):
        '''Check if Adjacency object is empty'''
        return bool(self.matrix_type == 'empty')

    def squareform(self):
        '''Convert adjacency back to squareform'''
        if self.issymmetric:
            if self.is_single_matrix:
                return squareform(self.data)
            else:
                return [squareform(x.data) for x in self]
        else:
            if self.is_single_matrix:
                return self.data.reshape(int(np.sqrt(self.data.shape[0])),
                                         int(np.sqrt(self.data.shape[0])))
            else:
                return [x.data.reshape(int(np.sqrt(x.data.shape[0])),
                                       int(np.sqrt(x.data.shape[0]))) for x in self]

    def plot(self, limit=3, *args, **kwargs):
        ''' Create Heatmap of Adjacency Matrix'''

        if self.is_single_matrix:
            f, a = plt.subplots(nrows=1, figsize=(7, 5))
            if self.labels is None:
                sns.heatmap(self.squareform(), square=True, ax=a,
                            *args, **kwargs)
            else:
                sns.heatmap(self.squareform(), square=True, ax=a,
                            xticklabels=self.labels,
                            yticklabels=self.labels,
                            *args, **kwargs)
        else:
            n_subs = np.minimum(len(self), limit)
            f, a = plt.subplots(nrows=n_subs, figsize=(7, len(self)*5))
            if self.labels is None:
                for i in range(n_subs):
                    sns.heatmap(self[i].squareform(), square=True, ax=a[i],
                                *args, **kwargs)
            else:
                for i in range(n_subs):
                    sns.heatmap(self[i].squareform(), square=True,
                                xticklabels=self.labels[i],
                                yticklabels=self.labels[i],
                                ax=a[i], *args, **kwargs)
        return f

    def mean(self, axis=0):
        ''' Calculate mean of Adjacency

        Args:
            axis:  (int) calculate mean over features (0) or data (1).
                    For data it will be on upper triangle.

        Returns:
            mean:  float if single, adjacency if axis=0, np.array if axis=1
                    and multiple

        '''

        if self.is_single_matrix:
            return np.mean(self.data)
        else:
            if axis == 0:
                return Adjacency(data=np.mean(self.data, axis=axis),
                                 matrix_type=self.matrix_type + '_flat')
            elif axis == 1:
                return np.mean(self.data, axis=axis)

    def std(self, axis=0):
        ''' Calculate standard deviation of Adjacency

        Args:
            axis:  (int) calculate std over features (0) or data (1).
                    For data it will be on upper triangle.

        Returns:
            std:  float if single, adjacency if axis=0, np.array if axis=1 and
                    multiple

        '''

        if self.is_single_matrix:
            return np.std(self.data)
        else:
            if axis == 0:
                return Adjacency(data=np.std(self.data, axis=axis),
                                 matrix_type=self.matrix_type + '_flat')
            elif axis == 1:
                return np.std(self.data, axis=axis)

    def shape(self):
        ''' Calculate shape of data. '''
        return self.data.shape

    def square_shape(self):
        ''' Calculate shape of squareform data. '''
        if self.matrix_type == 'empty':
            return np.array([])
        else:
            if self.is_single_matrix:
                return self.squareform().shape
            else:
                return self[0].squareform().shape

    def copy(self):
        ''' Create a copy of Adjacency object.'''
        return deepcopy(self)

    def append(self, data):
        ''' Append data to Adjacency instance

        Args:
            data:  (Adjacency) Adjacency instance to append

        Returns:
            out: (Adjacency) new appended Adjacency instance

        '''

        if not isinstance(data, Adjacency):
            raise ValueError('Make sure data is a Adjacency instance.')

        if self.isempty():
            out = data.copy()
        else:
            out = self.copy()
            if self.square_shape() != data.square_shape():
                raise ValueError('Data is not the same shape as Adjacency '
                                 'instance.')

            out.data = np.vstack([self.data, data.data])
            out.is_single_matrix = False
            if out.Y.size:
                out.Y = self.Y.append(data.Y)

        return out

    def write(self, file_name, method='long'):
        ''' Write out Adjacency object to csv file.

            Args:
                file_name (str):  name of file name to write
                method (str):     method to write out data ['long','square']

        '''
        if method not in ['long', 'square']:
            raise ValueError('Make sure method is ["long","square"].')
        if self.is_single_matrix:
            if method == 'long':
                pd.DataFrame(self.data).to_csv(file_name, index=None)
            elif method == 'square':
                pd.DataFrame(self.squareform()).to_csv(file_name, index=None)
        else:
            if method == 'long':
                pd.DataFrame(self.data).to_csv(file_name, index=None)
            elif method == 'square':
                raise NotImplementedError('Need to decide how we should write '
                                          'out multiple matrices.  As separate '
                                          'files?')

    def similarity(self, data, plot=False, perm_type='2d', n_permute=5000,
                   metric='spearman', **kwargs):
        ''' Calculate similarity between two Adjacency matrices.
        Default is to use spearman correlation and permutation test.
        Args:
            data: Adjacency data, or 1-d array same size as self.data
            perm_type: (str) '1d','2d', 'jackknife', or None
            metric: (str) 'spearman','pearson','kendall'
        '''
        data1 = self.copy()
        if not isinstance(data, Adjacency):
            data2 = Adjacency(data)
        else:
            data2 = data.copy()

        if perm_type is None:
            n_permute = 0
            similarity_func = correlation_permutation
        elif perm_type == '1d':
            similarity_func = correlation_permutation
        elif perm_type == '2d':
            similarity_func = matrix_permutation
        elif perm_type == 'jackknife':
            similarity_func = jackknife_permutation
        else:
            raise ValueError("perm_type must be ['1d','2d', 'jackknife', or None']")

        def _convert_data_similarity(data, perm_type=None):
            '''Helper function to convert data correctly'''
            if perm_type is None:
                data = data.data
            elif perm_type == '1d':
                data = data.data
            elif perm_type == '2d':
                data = data.squareform()
            elif perm_type == 'jackknife':
                data = data.squareform()
            else:
                raise ValueError("perm_type must be ['1d','2d', 'jackknife', or None']")
            return data

        if self.is_single_matrix:
            if plot:
                plot_stacked_adjacency(self, data)
            return similarity_func(_convert_data_similarity(data1,
                                                            perm_type=perm_type),
                                   _convert_data_similarity(data2,
                                                            perm_type=perm_type),
                                   metric=metric, n_permute=n_permute, **kwargs)
        else:
            if plot:
                _, a = plt.subplots(len(self))
                for i in a:
                    plot_stacked_adjacency(self, data, ax=i)
            return [similarity_func(_convert_data_similarity(x,
                                                             perm_type=perm_type),
                                    _convert_data_similarity(data2,
                                                             perm_type=perm_type),
                                    metric=metric, n_permute=n_permute,
                                    **kwargs) for x in self]

    def distance(self, method='correlation', **kwargs):
        ''' Calculate distance between images within an Adjacency() instance.

        Args:
            method: (str) type of distance metric (can use any scikit learn or
                    sciypy metric)

        Returns:
            dist: (Adjacency) Outputs a 2D distance matrix.

        '''
        return Adjacency(pairwise_distances(self.data, metric=method, **kwargs),
                         matrix_type='distance')

    def threshold(self, upper=None, lower=None, binarize=False):
        '''Threshold Adjacency instance. Provide upper and lower values or
           percentages to perform two-sided thresholding. Binarize will return
           a mask image respecting thresholds if provided, otherwise respecting
           every non-zero value.

        Args:
            upper: (float or str) Upper cutoff for thresholding. If string
                    will interpret as percentile; can be None for one-sided
                    thresholding.
            lower: (float or str) Lower cutoff for thresholding. If string
                    will interpret as percentile; can be None for one-sided
                    thresholding.
            binarize (bool): return binarized image respecting thresholds if
                    provided, otherwise binarize on every non-zero value;
                    default False

        Returns:
            Adjacency: thresholded Adjacency instance

        '''

        b = self.copy()
        if isinstance(upper, six.string_types):
            if upper[-1] == '%':
                upper = np.percentile(b.data, float(upper[:-1]))
        if isinstance(lower, six.string_types):
            if lower[-1] == '%':
                lower = np.percentile(b.data, float(lower[:-1]))

        if upper and lower:
            b.data[(b.data < upper) & (b.data > lower)] = 0
        elif upper and not lower:
            b.data[b.data < upper] = 0
        elif lower and not upper:
            b.data[b.data > lower] = 0
        if binarize:
            b.data[b.data != 0] = 1
        return b

    def to_graph(self):
        ''' Convert Adjacency into networkx graph.  only works on
            single_matrix for now.'''

        if self.is_single_matrix:
            if self.matrix_type == 'directed':
                G = nx.DiGraph(self.squareform())
            else:
                G = nx.Graph(self.squareform())
            if self.labels is not None:
                labels = {x: y for x, y in zip(G.nodes, self.labels)}
                nx.relabel_nodes(G, labels, copy=False)
            return G
        else:
            raise NotImplementedError('This function currently only works on '
                                      'single matrices.')

    def ttest(self, permutation=False, **kwargs):
        ''' Calculate ttest across samples.

        Args:
            permutation: (bool) Run ttest as permutation. Note this can be very slow.

        Returns:
            out: (dict) contains Adjacency instances of t values (or mean if
                 running permutation) and Adjacency instance of p values.

        '''
        if self.is_single_matrix:
            raise ValueError('t-test cannot be run on single matrices.')

        if permutation:
            t = []
            p = []
            for i in range(self.data.shape[1]):
                stats = one_sample_permutation(self.data[:, i], **kwargs)
                t.append(stats['mean'])
                p.append(stats['p'])
            t = Adjacency(np.array(t))
            p = Adjacency(np.array(p))
        else:
            t = self.mean().copy()
            p = deepcopy(t)
            t.data, p.data = ttest_1samp(self.data, 0, 0)

        return {'t': t, 'p': p}

    def plot_label_distance(self, labels=None, ax=None):
        ''' Create a violin plot indicating within and between label distance

            Args:
                labels (np.array):  numpy array of labels to plot

            Returns:
                f: violin plot handles

        '''

        if not self.is_single_matrix:
            raise ValueError('This function only works on single adjacency '
                             'matrices.')

        distance = pd.DataFrame(self.squareform())

        if labels is None:
            labels = np.array(deepcopy(self.labels))
        else:
            if len(labels) != distance.shape[0]:
                raise ValueError('Labels must be same length as distance matrix')

        out = pd.DataFrame(columns=['Distance', 'Group', 'Type'], index=None)
        for i in np.unique(labels):
            tmp_w = pd.DataFrame(columns=out.columns, index=None)
            tmp_w['Distance'] = distance.loc[labels == i, labels == i].values[np.triu_indices(sum(labels == i), k=1)]
            tmp_w['Type'] = 'Within'
            tmp_w['Group'] = i
            tmp_b = pd.DataFrame(columns=out.columns, index=None)
            tmp_b['Distance'] = distance.loc[labels != i, labels != i].values[np.triu_indices(sum(labels == i), k=1)]
            tmp_b['Type'] = 'Between'
            tmp_b['Group'] = i
            out = out.append(tmp_w).append(tmp_b)
        f = sns.violinplot(x="Group", y="Distance", hue="Type", data=out, split=True, inner='quartile',
                           palette={"Within": "lightskyblue", "Between": "red"}, ax=ax)
        f.set_ylabel('Average Distance')
        f.set_title('Average Group Distance')
        return f

    def stats_label_distance(self, labels=None, n_permute=5000, n_jobs=-1):
        ''' Calculate permutation tests on within and between label distance.

            Args:
                labels (np.array):  numpy array of labels to plot
                n_permute (int): number of permutations to run (default=5000)

            Returns:
                dict:  dictionary of within and between group differences
                        and p-values

        '''

        if not self.is_single_matrix:
            raise ValueError('This function only works on single adjacency '
                             'matrices.')

        distance = pd.DataFrame(self.squareform())

        if labels is not None:
            labels = deepcopy(self.labels)
        else:
            if len(labels) != distance.shape[0]:
                raise ValueError('Labels must be same length as distance matrix')

        out = pd.DataFrame(columns=['Distance', 'Group', 'Type'], index=None)
        for i in np.unique(labels):
            tmp_w = pd.DataFrame(columns=out.columns, index=None)
            tmp_w['Distance'] = distance.loc[labels == i, labels == i].values[np.triu_indices(sum(labels == i), k=1)]
            tmp_w['Type'] = 'Within'
            tmp_w['Group'] = i
            tmp_b = pd.DataFrame(columns=out.columns, index=None)
            tmp_b['Distance'] = distance.loc[labels == i, labels != i].values.flatten()
            tmp_b['Type'] = 'Between'
            tmp_b['Group'] = i
            out = out.append(tmp_w).append(tmp_b)
        stats = dict()
        for i in np.unique(labels):
            # Within group test
            tmp1 = out.loc[(out['Group'] == i) & (out['Type'] == 'Within'), 'Distance']
            tmp2 = out.loc[(out['Group'] == i) & (out['Type'] == 'Between'), 'Distance']
            stats[str(i)] = two_sample_permutation(tmp1, tmp2,
                                                   n_permute=n_permute, n_jobs=n_jobs)
        return stats

    def plot_silhouette(self, labels=None, ax=None, permutation_test=True,
                        n_permute=5000, **kwargs):
        '''Create a silhouette plot'''
        distance = pd.DataFrame(self.squareform())

        if labels is None:
            labels = np.array(deepcopy(self.labels))
        else:
            if len(labels) != distance.shape[0]:
                raise ValueError('Labels must be same length as distance matrix')

        (f, outAll) = plot_silhouette(distance, labels, ax=None,
                                      permutation_test=True,
                                      n_permute=5000, **kwargs)
        return (f, outAll)

    def bootstrap(self, function, n_samples=5000, save_weights=False,
                  n_jobs=-1, random_state=None, *args, **kwargs):
        '''Bootstrap an Adjacency method.

            Example Useage:
            b = dat.bootstrap('mean', n_samples=5000)
            b = dat.bootstrap('predict', n_samples=5000, algorithm='ridge')
            b = dat.bootstrap('predict', n_samples=5000, save_weights=True)

        Args:
            function: (str) method to apply to data for each bootstrap
            n_samples: (int) number of samples to bootstrap with replacement
            save_weights: (bool) Save each bootstrap iteration
                        (useful for aggregating many bootstraps on a cluster)
            n_jobs: (int) The number of CPUs to use to do the computation.
                        -1 means all CPUs.Returns:
        output: summarized studentized bootstrap output

        '''

        random_state = check_random_state(random_state)
        seeds = random_state.randint(MAX_INT, size=n_samples)
        bootstrapped = Parallel(n_jobs=n_jobs)(
                        delayed(_bootstrap_apply_func)(self,
                                                       function, random_state=seeds[i], *args, **kwargs)
                        for i in range(n_samples))
        bootstrapped = Adjacency(bootstrapped)
        return summarize_bootstrap(bootstrapped, save_weights=save_weights)

    def plot_mds(self, n_components=2, metric=True, labels_color=None,
                 cmap=plt.cm.hot_r, n_jobs=-1, view=(30, 20),
                 figsize=[12, 8], ax=None, *args, **kwargs):
        ''' Plot Multidimensional Scaling

            Args:
                n_components: (int) Number of dimensions to project (can be 2 or 3)
                metric: (bool) Perform metric or non-metric dimensional scaling; default
                labels_color: (str) list of colors for labels, if len(1) then make all same color
                n_jobs: (int) Number of parallel jobs
                view: (tuple) view for 3-Dimensional plot; default (30,20)

            Returns:
                fig: returns matplotlib figure
        '''

        if self.matrix_type != 'distance':
            raise ValueError("MDS only works on distance matrices.")
        if not self.is_single_matrix:
            raise ValueError("MDS only works on single matrices.")
        if n_components not in [2, 3]:
            raise ValueError('Cannot plot {0}-d image'.format(n_components))
        if labels_color is not None:
            if self.labels is None:
                raise ValueError("Make sure that Adjacency object has labels specified.")
            if len(self.labels) != len(labels_color):
                raise ValueError("Length of labels_color must match self.labels.")

        # Run MDS
        mds = MDS(n_components=n_components, metric=metric, n_jobs=n_jobs,
                  dissimilarity="precomputed", *args, **kwargs)
        proj = mds.fit_transform(self.squareform())

        # Create Plot
        if ax is None:  # Create axis
            returnFig = True
            fig = plt.figure(figsize=figsize)
            if n_components == 3:
                ax = fig.add_subplot(111, projection='3d')
                ax.view_init(*view)
            elif n_components == 2:
                ax = fig.add_subplot(111)

        # Plot dots
        if n_components == 3:
            ax.scatter(proj[:, 0], proj[:, 1], proj[:, 2], s=1, c='k')
        elif n_components == 2:
            ax.scatter(proj[:, 0], proj[:, 1], s=1, c='k')

        # Plot labels
        if labels_color is None:
            labels_color = ['black'] * len(self.labels)
        if n_components == 3:
            for ((x, y, z), label, color) in zip(proj, self.labels, labels_color):
                ax.text(x, y, z, label, color='white', bbox=dict(facecolor=color, alpha=1, boxstyle="round,pad=0.3"))
        else:
            for ((x, y), label, color) in zip(proj, self.labels, labels_color):
                ax.text(x, y, label, color='white',  # color,
                        bbox=dict(facecolor=color, alpha=1, boxstyle="round,pad=0.3"))

        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        if returnFig:
            return fig

    def distance_to_similarity(self, beta=1):
        '''Convert distance matrix to similarity matrix

        Args:
            beta: (float) parameter to scale exponential function (default: 1)

        Returns:
            out: (Adjacency) Adjacency object

        '''
        if self.matrix_type == 'distance':
            return Adjacency(np.exp(-beta*self.squareform()/self.squareform().std()),
                             labels=self.labels, matrix_type='similarity')
        else:
            raise ValueError('Matrix is not a distance matrix.')

    def similarity_to_distance(self):
        '''Convert similarity matrix to distance matrix'''
        if self.matrix_type == 'similarity':
            return Adjacency(1-self.squareform(),
                             labels=self.labels, matrix_type='distance')
        else:
            raise ValueError('Matrix is not a similarity matrix.')

    def within_cluster_mean(self, clusters=None):
        ''' This function calculates mean within cluster labels

        Args:
            clusters: (list) list of cluster labels
        Returns:
            dict: (dict) within cluster means
        '''

        distance = pd.DataFrame(self.squareform())
        clusters = np.array(clusters)

        if len(clusters) != distance.shape[0]:
            raise ValueError('Cluster labels must be same length as distance matrix')

        out = pd.DataFrame(columns=['Mean', 'Label'], index=None)
        out = {}
        for i in list(set(clusters)):
            out[i] = np.mean(distance.loc[clusters == i, clusters == i].values[np.triu_indices(sum(clusters == i), k=1)])
        return out

    def regress(self, X, mode='ols', **kwargs):
        ''' Run a regression on an adjacency instance.
            You can decompose an adjacency instance with another adjacency instance.
            You can also decompose each pixel by passing a design_matrix instance.

            Args:
                X: Design matrix can be an Adjacency or Design_Matrix instance
                method: type of regression (default: ols)

            Returns:
                stats: (dict) dictionary of stats outputs.
        '''

        stats = {}
        if isinstance(X, Adjacency):
            if X.square_shape()[0] != self.square_shape()[0]:
                raise ValueError('Adjacency instances must be the same size.')
            b, t, p, _, res = regression(X.data.T, self.data, mode=mode, **kwargs)
            stats['beta'], stats['t'], stats['p'], stats['residual'] = (b, t, p, res)
        elif isinstance(X, Design_Matrix):
            if X.shape[0] != len(self):
                raise ValueError('Design matrix must have same number of observations as Adjacency')
            b, t, p, df, res = regression(X, self.data, mode=mode, **kwargs)
            mode = 'ols'
            stats['beta'], stats['t'], stats['p'] = [x for x in self[:3]]
            stats['beta'].data, stats['t'].data, stats['p'].data = b.squeeze(), t.squeeze(), p.squeeze()
            stats['residual'] = self.copy()
            stats['residual'].data = res
        else:
            raise ValueError('X must be a Design_Matrix or Adjacency Instance.')

        return stats
