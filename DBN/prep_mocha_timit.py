import theano, copy, sys
import theano.tensor as T
import cPickle
import numpy as np

BORROW = True
USE_CACHING = False # beware if you use RBM / GRBM alternatively, set it to False

def padding(nframes, x, y):
    # dirty hacky padding
    ba = (nframes - 1) / 2 # before // after
    x2 = copy.deepcopy(x)
    on_x2 = False
    x_f = np.zeros((x.shape[0], nframes * x.shape[1]), dtype='float32')
    for i in xrange(x.shape[0]):
        if y[i] == '!ENTER[2]' and y[i-1] != '!ENTER[2]': # TODO general case
            on_x2 = not on_x2
            if on_x2:
                x2[i - ba:i,:] = 0.0
            else:
                x[i - ba:i,:] = 0.0
        if i+ba < y.shape[0] and '!EXIT' in y[i] and not '!EXIT' in y[i+ba]: # TODO general
            if on_x2:
                x2[i+ba:i+2*ba+1,:] = 0.0
            else:
                x[i+ba:i+2*ba+1,:] = 0.0
        if on_x2:
            x_f[i] = np.pad(x2[max(0, i - ba):i + ba + 1].flatten(),
                    (max(0, (ba - i) * x.shape[1]), 
                        max(0, ((i+ba+1) - x.shape[0]) * x.shape[1])),
                    'constant', constant_values=(0,0))
        else:
            x_f[i] = np.pad(x[max(0, i - ba):i + ba + 1].flatten(),
                    (max(0, (ba - i) * x.shape[1]), 
                        max(0, ((i+ba+1) - x.shape[0]) * x.shape[1])),
                    'constant', constant_values=(0,0))
    return x_f


def prep_data(dataset, nframes_mfcc=1, nframes_arti=1, unit=False, 
              normalize=False, pca_whiten_mfcc=0, pca_whiten_arti=0):
    """ Prepare the data for DBN learning.

    pca_whiten_mfcc and pca_whiten_arti are directly passed to PCA as:

    n_components : int, None or string
          Number of components to keep.
          if n_components is not set all components are kept::

              n_components == min(n_samples, n_features)

          if n_components == 'mle', Minka's MLE is used to guess the dimension
          if ``0 < n_components < 1``, select the number of components such that
          the amount of variance that needs to be explained is greater than the
          percentage specified by n_components
    """

    try:
        train_x = np.load(dataset + "/aligned_train_xdata.npy")
        train_y = np.load(dataset + "/aligned_train_ylabels.npy")
        test_x = np.load(dataset + "/aligned_test_xdata.npy")
        test_y = np.load(dataset + "/aligned_test_ylabels.npy")

    except:
        print >> sys.stderr, "you need the .npy python arrays"
        print >> sys.stderr, "you can produce them with src/timit_to_numpy.py"
        print >> sys.stderr, "applied to the HTK force-aligned MLF train/test files"
        print >> sys.stderr, dataset + "/aligned_train_xdata.npy"
        print >> sys.stderr, dataset + "/aligned_train_ylabels.npy"
        print >> sys.stderr, dataset + "/aligned_test_xdata.npy"
        print >> sys.stderr, dataset + "/aligned_test_ylabels.npy"
        sys.exit(-1)

    print "train_x shape:", train_x.shape

    n_mfcc = 39
    if pca_whiten_mfcc:
        ### PCA whitening, beware it's sklearn's and thus stays in PCA space
        from sklearn.decomposition import PCA
        pca = PCA(n_components=pca_whiten_mfcc, whiten=True)
        pca.fit(train_x[:, :n_mfcc])
        n_mfcc = pca.n_components
        # and thus here we still never saw test data
        train_x = np.concatenate([pca.transform(train_x[:, :n_mfcc]),
                                 train_x[:, n_mfcc:]], axis=1)
        test_x = np.concatenate([pca.transform(test_x[:, :n_mfcc]),
                                 test_x[:, n_mfcc:]], axis=1)
    n_arti = 60
    if pca_whiten_arti:
        ### PCA whitening, beware it's sklearn's and thus stays in PCA space
        from sklearn.decomposition import PCA
        pca = PCA(n_components=pca_whiten_arti, whiten=True)
        pca.fit(train_x[:, n_mfcc:])
        n_arti = pca.n_components
        # and thus here we still never saw test data
        train_x = np.concatenate([train_x[:, :n_mfcc],
                                 pca.transform(train_x[:, n_mfcc:])], axis=1)
        test_x = np.concatenate([test_x[:, :n_mfcc],
                                 pca.transform(test_x[:, n_mfcc:])], axis=1)
    if unit:
        ### Putting values on [0-1]
        # TODO or do that globally on all data
        train_x = (train_x - np.min(train_x, 0)) / np.max(train_x, 0)
        test_x = (test_x - np.min(test_x, 0)) / np.max(test_x, 0)
    if normalize:
        ### Normalizing (0 mean, 1 variance)
        # TODO or do that globally on all data
        train_x = (train_x - np.mean(train_x, 0)) / np.std(train_x, 0)
        test_x = (test_x - np.mean(test_x, 0)) / np.std(test_x, 0)
    train_x_f_mfcc = train_x[:, :39]
    train_x_f_arti = train_x[:, 39:]
    test_x_f_mfcc = test_x[:, :39]
    test_x_f_arti = test_x[:, 39:]

    ### Feature values (Xs)
    print "preparing / padding Xs"
    if nframes_mfcc > 1:
        train_x_f_mfcc = padding(nframes_mfcc, train_x[:, :39], train_y)
        test_x_f_mfcc = padding(nframes_mfcc, test_x[:, :39], test_y)
    if nframes_arti > 1:
        train_x_f_arti = padding(nframes_arti, train_x[:, 39:], train_y)
        test_x_f_arti = padding(nframes_arti, test_x[:, 39:], test_y)
    if nframes_arti == 0:
        train_x_f_arti = np.ndarray((train_x_f_mfcc.shape[0], 0), dtype='float32')
        test_x_f_arti = np.ndarray((test_x_f_mfcc.shape[0], 0), dtype='float32')

    ### Labels (Ys)
    from collections import Counter
    c = Counter(train_y)
    to_int = dict([(k, c.keys().index(k)) for k in c.iterkeys()])
    to_state = dict([(c.keys().index(k), k) for k in c.iterkeys()])
    with open('to_int_and_to_state_dicts_tuple_mocha.pickle', 'w') as f:
        cPickle.dump((to_int, to_state), f)

    print "preparing / int mapping Ys"
    train_y_f = np.zeros(train_y.shape[0], dtype='int32')
    for i, e in enumerate(train_y):
        train_y_f[i] = to_int[e]

    test_y_f = np.zeros(test_y.shape[0], dtype='int32')
    for i, e in enumerate(test_y):
        test_y_f[i] = to_int[e]

    return ([np.concatenate([train_x_f_mfcc, train_x_f_arti], axis=1), train_y_f, 
            np.concatenate([test_x_f_mfcc, test_x_f_arti], axis=1), test_y_f],
            n_mfcc, n_arti)

def load_data(dataset, nframes_mfcc=11, nframes_arti=5, 
              unit=False, normalize=False, 
              pca_whiten_mfcc=0, pca_whiten_arti=0, cv_frac=0.2):
    def prep_and_serialize():
        ([train_x, train_y, test_x, test_y], n_mfcc, n_arti) = prep_data(
                dataset, 
                nframes_mfcc=nframes_mfcc, nframes_arti=nframes_arti,
                unit=unit, normalize=normalize, 
                pca_whiten_mfcc=pca_whiten_mfcc, 
                pca_whiten_arti=pca_whiten_arti)
        with open('train_x_mocha.npy', 'w') as f:
            np.save(f, train_x)
        with open('train_y_mocha.npy', 'w') as f:
            np.save(f, train_y)
        with open('test_x_mocha.npy', 'w') as f:
            np.save(f, test_x)
        with open('test_y_mocha.npy', 'w') as f:
            np.save(f, test_y)
        print ">>> Serialized all train/test tables"
        return ([train_x, train_y, test_x, test_y], n_mfcc, n_arti)

    if USE_CACHING:
        try: # try to load from serialized filed, bewa
            with open('train_x_mocha.npy') as f:
                train_x = np.load(f)
            with open('train_y_mocha.npy') as f:
                train_y = np.load(f)
            with open('test_x_mocha.npy') as f:
                test_x = np.load(f)
            with open('test_y_mocha.npy') as f:
                test_y = np.load(f)
        except: # do the whole preparation (normalization / padding)
            ([train_x, train_y, test_x, test_y], n_mfcc, n_arti) = prep_and_serialize()
    else:
        ([train_x, train_y, test_x, test_y], n_mfcc, n_arti) = prep_and_serialize()

    from sklearn import cross_validation
    X_train, X_validate, y_train, y_validate = cross_validation.train_test_split(train_x, train_y, test_size=cv_frac, random_state=0)
    
    train_set_x = theano.shared(X_train, borrow=BORROW)
    train_set_y = theano.shared(np.asarray(y_train, dtype=theano.config.floatX), borrow=BORROW)
    train_set_y = T.cast(train_set_y, 'int32')
    val_set_x = theano.shared(X_validate, borrow=BORROW)
    val_set_y = theano.shared(np.asarray(y_validate, dtype=theano.config.floatX), borrow=BORROW)
    val_set_y = T.cast(val_set_y, 'int32')
    test_set_x = theano.shared(test_x, borrow=BORROW)
    test_set_y = theano.shared(np.asarray(test_y, dtype=theano.config.floatX), borrow=BORROW)
    test_set_y = T.cast(test_set_y, 'int32')
    return ([(train_set_x, train_set_y), 
            #(copy.deepcopy(test_set_x), copy.deepcopy(test_set_y)),
            (val_set_x, val_set_y),
            (test_set_x, test_set_y)], n_mfcc, n_arti)