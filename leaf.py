from ipywidgets import IntProgress, HTML, HBox, Label
from IPython.display import display
import copy, mock
import numpy as np
import numpy.linalg as linalg
import matplotlib.pyplot as plt
import pandas as pd
import sklearn, scipy
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, precision_score, recall_score
from scipy.spatial.distance import pdist, cdist
from sklearn.model_selection import train_test_split

import shap
import lime
from lime.lime_tabular import LimeTabularExplainer

###########################################################################################

###########################################################################################

# Build the linear classifier of a LIME explainer
def get_LIME_classifier(lime_expl, label_x0, x0):
    features_weights = [x[1] for x in lime_expl.local_exp[label_x0]]
    features_indices = [x[0] for x in lime_expl.local_exp[label_x0]]    # feature' indices
    intercept = lime_expl.intercept[label_x0]
    coef = np.zeros(len(x0))
    coef[features_indices] = features_weights
    if hasattr(lime_expl, 'perfect_local_concordance') and lime_expl.perfect_local_concordance:

        g = lime.lime_base.TranslatedRidge(alpha=1.0)
        g.x0 = np.zeros(len(x0))
        g.x0 = lime_expl.x0

        g.f_x0 = lime_expl.predict_proba[label_x0]
        g.coef_ = g.ridge.coef_ = coef
        g.intercept_ = g.ridge.intercept_ = intercept
        
    else:
        g = sklearn.linear_model.Ridge(alpha=1.0, fit_intercept=True)
        g.coef_ = coef
        g.intercept_ = intercept
    return g

# Build the linear classifier of a SHAP explainer
def get_SHAP_classifier(label_x0, phi, phi0, x0, EX):
    coef = np.divide(phi[label_x0], (x0 - EX), where=(x0 - EX)!=0)
    g = sklearn.linear_model.Ridge(alpha=1.0, fit_intercept=True)
    g.coef_ = coef
    g.intercept_ = phi0[label_x0]
    return g

###########################################################################################

def eval_whitebox_classifier(R, g, EX, StdX, NormV, x0, label_x0, bb_classifier, wb_name,
                             precision_recalls=False):
    # scale x0 in the ridge model space
    sx0 = np.divide((x0 - EX), StdX, where=np.logical_not(np.isclose(StdX, 0)))

    sx0_w = np.dot(sx0, g.coef_)
    p_score = sx0_w + g.intercept_

    if linalg.norm(g.coef_) < 1.0e-5 or (abs(sx0_w) < 1.0e-5):
        N_sx0_w = np.zeros(len(x0))
        R.wb_plane_dist_x0 = 0.0
    else:
        N_sx0_w = np.multiply(sx0, (0.5 - p_score) / sx0_w)
        R.wb_plane_dist_x0 = p_score / linalg.norm(g.coef_)

    # get the boundary point x1
    sx1 = sx0 + N_sx0_w
    x1 = (sx1 * StdX) + EX

    prob_x1 = bb_classifier(np.array([x1]))[0]
    R.wb_class_x1 = 1 if prob_x1[1] > prob_x1[0] else 0
    R.wb_prob_x1_F = prob_x1[0]
    R.wb_prob_x1_T = prob_x1[1]
    R.wb_prob_x1_c0 = prob_x1[label_x0]

    R.wb_local_discr = g.predict([sx0])[0] - R.prob_x0
    R.wb_boundary_discr = g.predict([sx1])[0] - prob_x1[0]

    # build the (scaled) neighborhood of x0
    SNX0 = np.tile(sx0, (NormV.shape[0], 1)) # repeat T times the scaled x1 row
    SNX0 = SNX0 + NormV
    NX0 = (SNX0 * StdX) + EX

    # build the (scaled) neighborhood of x1
    SNX1 = np.tile(sx1, (NormV.shape[0], 1)) # repeat T times the scaled x1 row
    SNX1 = SNX1 + NormV
    NX1 = (SNX1 * StdX) + EX

    # predict the instance classes using the Black-Box and the White-Box classifiers 
    BBY0, WBY0 = bb_classifier(NX0)[:,0], g.predict(SNX0)
    BBY1, WBY1 = bb_classifier(NX1)[:,0], g.predict(SNX1)
    if label_x0 == 1:
        WBY0, WBY1 = 1 - WBY0, 1 - WBY1
    BBCLS0, WBCLS0 = BBY0 > 0.5, WBY0 > 0.5
    BBCLS1, WBCLS1 = BBY1 > 0.5, WBY1 > 0.5

    R.wb_x1_change_score = np.mean(BBCLS1 != label_x0)
    R.wb_avg_bb_nx0 = np.mean(BBY0)
    R.wb_avg_bb_nx1 = np.mean(BBY1)
    R.wb_ratio_x0 = np.mean(BBCLS0)
    R.wb_ratio_x1 = np.mean(BBCLS1)
    R.wb_ratio_wb_x0 = np.mean(WBCLS0)
    R.wb_ratio_wb_x1 = np.mean(WBCLS1)

    try:
        R.wb_fidelity = accuracy_score(BBCLS0, WBCLS0)
        R.wb_prescriptivity = accuracy_score(BBCLS1, WBCLS1)
        R.wb_bal_fidelity = balanced_accuracy_score(BBCLS0, WBCLS0)
        R.wb_bal_prescriptivity = balanced_accuracy_score(BBCLS1, WBCLS1)

        R.wb_fidelity_f1 = f1_score(BBCLS0, WBCLS0)
        R.wb_prescriptivity_f1 = f1_score(BBCLS1, WBCLS1)

        if precision_recalls:
            R.wb_precision_x1 = precision_score(BBCLS1, WBCLS1)
            R.wb_recall_x1 = recall_score(BBCLS1, WBCLS1)

    except:
        R.wb_bal_fidelity, R.wb_bal_prescriptivity = 0, 0
        R.wb_fidelity, R.wb_prescriptivity = 0, 0
        R.wb_fidelity_f1, R.wb_prescriptivity_f1 = 0, 0

    # rename R keys (wb_* -> wb_name_*)
    for key in copy.copy(list(R.__dict__.keys())):
        if key.startswith("wb_"):
            R.__dict__[wb_name + key[2:]] = R.__dict__.pop(key)

    return (x1, sx1)

###########################################################################################

def hinge_loss(x):
    return max(0, 1 - x)

###########################################################################################

class LEAF:
    def __init__(self, bb_classifier, X_full, y, class_names, explanation_samples=5000):
        _, X, _, _ = train_test_split(
            X_full, y, test_size=0.0005, stratify=y, random_state=0)
        self.bb_classifier = bb_classifier
        self.EX, self.StdX = np.mean(X), np.array(np.std(X, axis=0, ddof=0))
        self.class_names = class_names
        self.F = X.shape[1] # number of features
        self.explanation_samples = explanation_samples

        # SHAP Kernel
        self.SHAPEXPL = shap.KernelExplainer(self.bb_classifier.predict, X, nsamples=explanation_samples)

        # LIME Kernel
        self.LIMEEXPL = LimeTabularExplainer(X, 
	                                         feature_names=X.columns.tolist(), 
	                                         class_names=self.class_names, 
	                                         discretize_continuous=False,
	                                         sample_around_instance=True,
	                                         # categorical_features=categorical_features,
	                                         # feature_selection='highest_weights',
	                                         # sample_using_pca=False, 
	                                         # weight_classifier_labels=False,
	                                         random_state=10)
        self.metrics = None
        self.lime_avg_jaccard_bin = self.lime_std_jaccard_bin = None
        self.shap_avg_jaccard_bin = self.shap_std_jaccard_bin = None


    def explain_instance(self, instance, num_reps=50, num_features=4, 
                         neighborhood_samples=10000, use_cov_matrix=False, 
                         verbose=False, figure_dir=None):
        npEX = np.array(self.EX)
        cls_proba = self.bb_classifier.predict

        x0 = copy.deepcopy(instance) # instance to be explained
        mockobj = mock.Mock()

        # Neighborhood random samples
        cov_matrix = np.cov(((X - npEX) / self.StdX).T) if use_cov_matrix else 1.0
        NormV = scipy.stats.multivariate_normal.rvs(mean=np.zeros(self.F), cov=cov_matrix, 
                                                    size=neighborhood_samples, random_state=10)

        # Get the output of the black-box classifier on x0
        output = cls_proba(np.array([x0]))[0]
        label_x0 = np.argmax(output)
        prob_x0 = output[label_x0]
        prob_x0_F, prob_x0_T = output[0], output[1]
        if verbose:
            print('prob_x0',prob_x0,'   label_x0',self.class_names[label_x0])

        # Prepare instance for LIME
        lime_x0 = np.divide((x0 - npEX), self.StdX, where=np.logical_not(np.isclose(self.StdX, 0)))
        shap_x0 = (x0 - npEX)

        rows = None
        progbar = IntProgress(min=0, max=num_reps)
        label = Label(value="")
        display(HBox([Label("K=%d "%(num_features)), progbar, label]))

        # Explain the same instance x0 multiple times
        for rnum in range(num_reps):
            label.value = "%d/%d" % (rnum+1, num_reps)
            R = mock.Mock() # store all the computed metrics
            R.rnum, R.prob_x0 = rnum, prob_x0

            # Explain the instance x0 with LIME
            lime_expl = self.LIMEEXPL.explain_instance(np.array(x0), cls_proba, 
                                                       num_features=num_features, 
                                                       top_labels=1, 
                                                       num_samples=self.explanation_samples)

            # Explain x0 using SHAP
            shap_phi = self.SHAPEXPL.shap_values(x0, l1_reg="num_features(10)")
            shap_phi0 = self.SHAPEXPL.expected_value

            # Take only the top @num_features from shap_phi
            argtop = np.argsort(np.abs(shap_phi[0]))
            for k in range(len(shap_phi)):
                shap_phi[k][ argtop[:(self.F-num_features)] ] = 0

            # Recover both the LIME and the SHAP classifiers
            R.lime_g = get_LIME_classifier(lime_expl, label_x0, x0)
            R.shap_g = get_SHAP_classifier(label_x0, shap_phi, shap_phi0, x0, self.EX)

            #----------------------------------------------------------
            # Evaluate the white box classifiers
            EL = eval_whitebox_classifier(R, R.lime_g, npEX, self.StdX, 
                                          NormV, x0, label_x0, cls_proba, "lime", 
                                          precision_recalls=True)
            ES = eval_whitebox_classifier(R, R.shap_g, npEX, np.ones(len(x0)), 
                                          NormV * self.StdX, x0, label_x0, cls_proba, "shap", 
                                          precision_recalls=True)

            R.lime_local_discr = np.abs(R.lime_g.predict([lime_x0])[0] - prob_x0)
            R.shap_local_discr = np.abs(R.shap_g.predict([shap_x0])[0] - prob_x0)

            # Indices of the most important features, ordered by their absolute value
            R.lime_argtop = np.argsort(np.abs(R.lime_g.coef_))
            R.shap_argtop = np.argsort(np.abs(R.shap_g.coef_))

            # get the K most common features in the explanation of x0
            R.mcf_lime = tuple([R.lime_argtop[-k] for k in range(num_features)])
            R.mcf_shap = tuple([R.shap_argtop[-k] for k in range(num_features)])

            # Binary masks of the argtops
            R.lime_bin_expl, R.shap_bin_expl = np.zeros(self.F), np.zeros(self.F)
            R.lime_bin_expl[np.array(R.mcf_lime)] = 1
            R.shap_bin_expl[np.array(R.mcf_shap)] = 1

            # get the appropriate R keys
            R_keys = copy.copy(R.__dict__)
            for key in copy.copy(list(R_keys.keys())):
                if key.startswith("wb_"):
                    R_keys[wb_name + key[2:]] = R_keys.pop(key)
                elif key in mockobj.__dict__:
                    del R_keys[key]

            rows = pd.DataFrame(columns=R_keys) if rows is None else rows
            rows = rows._append({k:R.__dict__[k] for k in R_keys}, ignore_index=True)
            progbar.value += 1

        label.value += " Done."

        # use the multiple explanations to compute the LEAF metrics
        # display(rows)

        # Jaccard distances between the various explanations (stability)
        lime_jaccard_mat = 1 - pdist(np.stack(rows.lime_bin_expl, axis=0), 'jaccard')
        shap_jaccard_mat = 1 - pdist(np.stack(rows.shap_bin_expl, axis=0), 'jaccard')
        self.lime_avg_jaccard_bin, self.lime_std_jaccard_bin = np.mean(lime_jaccard_mat), np.std(lime_jaccard_mat)
        self.shap_avg_jaccard_bin, self.shap_std_jaccard_bin = np.mean(shap_jaccard_mat), np.std(shap_jaccard_mat)

        # LIME/SHAP explanation comparisons
        lime_shap_jaccard_mat = 1 - cdist(np.stack(rows.lime_bin_expl, axis=0), 
                                          np.stack(rows.shap_bin_expl, axis=0), 'jaccard')
        lime_shap_avg_jaccard_bin, lime_shap_std_jaccard_bin = np.mean(lime_shap_jaccard_mat), np.std(lime_shap_jaccard_mat)

        # store the metrics for later use
        self.metrics = rows

        def leaf_plot(stability, method):
            fig, ax1 = plt.subplots(figsize=(6, 2.2))
            data = [ stability.flatten(),
                     1 - rows[method + '_local_discr'], 
                     rows[method + '_fidelity_f1'], 
                     # rows[method + '_prescriptivity_f1'],
                     # rows[method + '_bal_prescriptivity' ],
                     1 - 2 * np.abs(rows[method + '_boundary_discr' ]) ]


            # color = 'tab:red'
            ax1.tick_params(axis='both', which='major', labelsize=12)
            ax1.set_xlabel('distribution')
            ax1.set_ylabel('LEAF metrics', color='black', fontsize=15)
            ax1.boxplot(data, vert=False, widths=0.7)
            ax1.tick_params(axis='y', labelcolor='#500000')
            ax1.set_yticks(np.arange(1, len(data)+1))
            ax1.set_yticklabels(['Stability', 'Local Concordance', 'Fidelity', 'Prescriptivity'])
            ax1.set_xlim([-0.05,1.05])
            ax1.invert_yaxis()

            ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis
            ax2.tick_params(axis='both', which='major', labelsize=12)
            ax2.set_ylabel('Values', color='#000080')  # we already handled the x-label with ax1
            ax2.boxplot(data, vert=False, widths=0.7)
            ax2.tick_params(axis='y', labelcolor='#000080')
            ax2.set_yticks(np.arange(1, len(data)+1))
            ax2.set_yticklabels([ "  %.3f ± %.3f  " % (np.mean(d), np.std(d)) for d in data])
            ax2.invert_yaxis()

            fig.tight_layout()  # otherwise the right y-label is slightly clipped
            if figure_dir is not None:
                imgname = figure_dir+method+"_leaf.pdf"
                print('Saving', imgname)
                plt.savefig(imgname, dpi=150, bbox_inches='tight')
            plt.show()

        # Show LIME explanation
        display(HTML("<h2>LIME</h2>"))
        lime_expl.show_in_notebook(show_table=True, show_all=False)
        leaf_plot(lime_jaccard_mat, 'lime')

        # Show SHAP explanation
        display(HTML("<h2>SHAP</h2>"))
        display(shap.force_plot(shap_phi0[label_x0], shap_phi[label_x0], x0))
        leaf_plot(shap_jaccard_mat, 'shap')

        prescription = False
        if prescription:
            print("====================================================")
            lime_x1, lime_sx1 = EL
            shap_x1, shap_sx1 = ES

            print('SHAP accuracy %f balanced_accuracy %f precision %f recall %f' % 
                  (rows.shap_prescriptivity.mean(), rows.shap_bal_prescriptivity.mean(),
                   rows.shap_precision_x1.mean(), rows.shap_recall_x1.mean()))

            lime_diff = (rows.iloc[-1].lime_g.coef_ != 0) * (lime_x1 - x0)
            shap_diff = (rows.iloc[-1].shap_g.coef_ != 0) * (shap_x1 - x0)

            print(np.array(rows.iloc[-1].lime_g.coef_ != 0))
            print('lime_diff\n', lime_diff)
            print('shap_diff\n', shap_diff)

            lime_output_x1 = cls_proba([lime_x1])[0]
            shap_output_x1 = cls_proba([shap_x1])[0]
            lime_label_x1 = 1 if lime_output_x1[1] >= lime_output_x1[0] else 0
            shap_label_x1 = 1 if shap_output_x1[1] >= shap_output_x1[0] else 0

            print("LIME(x1) prob =", lime_output_x1)
            print("SHAP(x1) prob =", shap_output_x1)

            # Show LIME explanation
            lime_expl = LIMEEXPL.explain_instance(np.array(shap_x1), cls_proba, 
                                                  num_features=num_features, 
                                                  top_labels=1, num_samples=self.explanation_samples)
            lime_expl.show_in_notebook(show_table=True, show_all=False)
            # leaf_plot(lime_jaccard_mat, 'lime')

            # Show SHAP explanation
            shap_phi = SHAPEXPL.shap_values(shap_x1, l1_reg="num_features(10)")
            shap_phi0 = SHAPEXPL.expected_value
            argtop = np.argsort(np.abs(shap_phi[0]))
            for k in range(len(shap_phi)):
                shap_phi[k][ argtop[:(F-num_features)] ] = 0
            display(shap.force_plot(shap_phi0[shap_label_x1], shap_phi[shap_label_x1], shap_x1))

    def get_R(self):
        return self.metrics

    #------------------------------------------#

    def get_lime_stability(self):
        assert self.metrics is not None
        return self.lime_avg_jaccard_bin

    def get_lime_local_concordance(self):
        assert self.metrics is not None
        return hinge_loss(np.mean(self.metrics.lime_local_discr))

    def get_lime_fidelity(self):
        assert self.metrics is not None
        return np.mean(self.metrics.lime_fidelity_f1)

    def get_lime_prescriptivity(self):
        assert self.metrics is not None
        return hinge_loss(np.mean(2 * np.abs(self.metrics.lime_boundary_discr)))

    #------------------------------------------#

    def get_shap_stability(self):
        assert self.metrics is not None
        return self.shap_avg_jaccard_bin

    def get_shap_local_concordance(self):
        assert self.metrics is not None
        return hinge_loss(np.mean(self.metrics.shap_local_discr))

    def get_shap_fidelity(self):
        assert self.metrics is not None
        return np.mean(self.metrics.shap_fidelity_f1)

    def get_shap_prescriptivity(self):
        assert self.metrics is not None
        return hinge_loss(np.mean(2 * np.abs(self.metrics.shap_boundary_discr)))

    #------------------------------------------#