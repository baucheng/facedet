import numpy as np
from predmaps import get_input_coords
from copy import copy


def include(a, b):
    """
    Return whether b is inside a
    """
    rval = (a[0]<=b[0] and a[1]<=b[1] and b[2]<=a[2] and b[3]<=a[3])
    return rval


def remove_inclusions(n_z_elems, model):
    """
    Remove elements included in other elements from the list
    """
    l = []
    for i, [s, x, y, sco] in enumerate(n_z_elems):
        [[x0, y0], [x1, y1]] = get_input_coords(x, y, model)
        a = np.array([x0/s, y0/s])
        b = np.array([(x0 + x1)/s, (y0+y1)/s])
        l.append([a[0], a[1], b[0], b[1], i])
    for i, e in enumerate(l):
        if e is None:
            continue
        for j, f in enumerate(l):
            if f is None or j==i:
                continue
            if include(e, f):
                l[j] = None
            elif include(f, e):
                l[i] = None
    rval = []
    for i, e in enumerate(l):
        if e is None:
            continue
        rval.append(n_z_elems[i])
    return rval


def get_rois(n_z_elems, model, enlarge_factor=0.0):
    """
    Return the coords of patches corresponding to
    non-zeros areas after nms execution
    rois : Regions of Interests
    ---------------------------------------------
    n_z_elems : list of non zero elements
               versions obtained after performing NMS
    pred_size : size of the input patch of the classifier
    pred_stride : stride of classification

    RETURNS :
    rois : a list of 2*2 np_arrays indicating areas of interests
    """
    n_z_elems = remove_inclusions(n_z_elems, model)
    rois = []
    scores = []
    for [s, x, y, sco] in n_z_elems:
        scores.append(sco)
        # Get coords on the zoomed image
        [[x0, y0], [x1, y1]] = get_input_coords(x, y, model)
        # Unzoom to get original coords
        a = np.array([x0/s, y0/s])
        b = np.array([(x0 + x1)/s, (y0+y1)/s])
        rois.append(np.vstack((a, b)))
    return rois, scores


def rois_to_slices(rois):
    """
    Returns slices made from RoIs so that
    img[rval[i]] return the pixels corresponding to a RoI
    ------------------------------------------------------
    rois : list of 2*2 np arrays that may contain valid coords
           considering img_shape
    """
    rval = copy(rois)
    for i, e in enumerate(rval):
        rval[i] = [slice(e[0, 0], e[1, 0]),
                   slice(e[0, 1], e[1, 1]), slice(None)]
    return rval


def correct_rois(rois, img_shape):
    """
    Returns the cropped RoIs so that they are valid regions of the image
    -------------------------------------------------------------------
    rois : list of 2*2 numpy arrays
           usually result of enlarge can return regions reaching indices
           out of image shape, this corrects it
    img_shape : shape of the image, 3 int tuple
    """
    rval = copy(rois)
    for i, e in enumerate(rval):
        # Necessary to avoid copy effects !
        f = np.copy(e)
        f[0, :] = np.maximum(f[0, :], np.zeros((2,)))
        f[1, :] = np.minimum(f[1, :], np.array([img_shape[0:2]]))
        rval[i] = f
    return rval


if __name__ == '__main__':
    a = [0, 0, 4, 4]
    b = [1, 1, 2, 2]
    print a
    print b
    print include(a, b)
    print include(b, a)
