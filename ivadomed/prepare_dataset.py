import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt
import PIL
import skimage
import os
import sys
import ivadomed.utils as imed_utils
import scipy

# normalize Image
def normalize(arr):
    ma = arr.max()
    mi = arr.min()
    return ((arr - mi) / (ma - mi))


# Useful function to generate a Gaussian Function on given coordinates. Used to generate ground truth.
def label2maskmap_gt(data, shape, c_dx=0, c_dy=0, radius=10, normalize=False):
    """
    Generate a heatmap resulting from the convolution between a 2D Gaussian kernel and a pair of 2D coordinates.
    Args:
        data: input image
        shape: dimension of output
        c_dx: shift along the x axis
        c_dy: shift along th y axis
        radius: is the radius of the gaussian function
        normalize: bool for normalization.

    Returns:
        array: a MxN normalized array

    """

    # Our 2-dimensional distribution will be over variables X and Y
    (M, N) = (shape[2], shape[1])
    if len(data) <= 2:
        # Output coordinates are reduced during post processing which poses a problem
        data = [0, data[0], data[1]]
    maskMap = []

    x, y = data[2], data[1]

    # Correct the labels
    x += c_dx
    y += c_dy

    X = np.linspace(0, M - 1, M)
    Y = np.linspace(0, N - 1, N)
    X, Y = np.meshgrid(X, Y)

    # Pack X and Y into a single 3-dimensional array
    pos = np.empty(X.shape + (2,))
    pos[:, :, 0] = X
    pos[:, :, 1] = Y

    # Mean vector and covariance matrix
    mu = np.array([x, y])
    Sigma = np.array([[radius, 0], [0, radius]])

    # The distribution on the variables X, Y packed into pos.
    Z = multivariate_gaussian(pos, mu, Sigma)

    # Normalization
    if normalize:
        Z *= (1 / np.max(Z))
    else:
        # 8bit image values (the loss go to inf+)
        Z *= (1 / np.max(Z))
        Z = np.asarray(Z * 255, dtype=np.uint8)

    maskMap.append(Z)

    if len(maskMap) == 1:
        maskMap = maskMap[0]

    return np.asarray(maskMap)


def gkern(kernlen=10):
    """Returns a 2D Gaussian kernel."""

    x = np.linspace(0, 1, kernlen+1)
    kern1d = np.diff(scipy.stats.norm.cdf(x))
    kern2d = np.outer(kern1d, kern1d)
    return normalize(kern2d/kern2d.sum())


def heatmap_generation(image, kernel_size):
    """
    Generate heatmap from image containing sing voxel label using
    convolution with gaussian kernel
    Args:
        image: 2D array containing single voxel label
        kernel_size: size of gaussian kernel

    Returns:
        array: 2d array heatmap matching the label.

    """
    kernel = gkern(kernel_size)
    map = scipy.signal.convolve(image, kernel)
    return normalize(map)


def multivariate_gaussian(pos, mu, Sigma):
    """
    Return the multivariate Gaussian distribution on array.

    pos is an array constructed by packing the meshed arrays of variables
    x_1, x_2, x_3, ..., x_k into its _last_ dimension.

    """

    n = mu.shape[0]
    Sigma_det = np.linalg.det(Sigma)
    Sigma_inv = np.linalg.inv(Sigma)
    N = np.sqrt((2 * np.pi) ** n * Sigma_det)
    # This einsum call calculates (x-mu)T.Sigma-1.(x-mu) in a vectorized
    # way across all the input variables.
    fac = np.einsum('...k,kl,...l->...', pos - mu, Sigma_inv, pos - mu)

    return np.exp(-fac / 2) / N


def add_zero_padding(img_list, x_val=512, y_val=512):
    """
    Add zero padding to each image in an array so they all have matching dimension.
    Args:
        img_list: list of input image to pad
        x_val: shape of output alongside x axis
        y_val: shape of output alongside y axis

    Returns:
        list of padded images
    """
    if type(img_list) != list:
        img_list = [img_list]
    img_zero_padding_list = []
    for i in range(len(img_list)):
        img = img_list[i]
        img_tmp = np.zeros((x_val, y_val, 1), dtype=np.float64)
        img_tmp[0:img.shape[0], 0:img.shape[1], 0] = img
        img_zero_padding_list.append(img_tmp)

    return img_zero_padding_list


def mask2label(path_label, aim='full'):
    """
    Convert nifti image to an array of coordinates
    :param path_label:
    :return:
    Args:
        path_label: path of nifti image
        aim: 'full' or 'c2' full will return all points with label between 3 and 30 , c2 will return only the coordinates of points label 3

    Returns:
        array: array containing the asked point in the format [x,y,z,value]

    """
    image = nib.load(path_label)
    image = nib.as_closest_canonical(image)
    arr = np.array(image.dataobj)
    list_label_image = []
    for i in range(len(arr.nonzero()[0])):
        x = arr.nonzero()[0][i]
        y = arr.nonzero()[1][i]
        z = arr.nonzero()[2][i]
        if aim == 'full':
            if arr[x, y, z] < 30 and arr[x, y, z] != 1:
                list_label_image.append([x, y, z, arr[x, y, z]])
        elif aim == 'c2':
            if arr[x, y, z] == 3:
                list_label_image.append([x, y, z, arr[x, y, z]])
    list_label_image.sort(key=lambda x : x[3])
    return list_label_image


def get_midslice_average(path_im, ind):
    """
    Retrieve the input images for the network. This images are generated by
    averaging the 7 slices in the middle of the volume
    :param path_im:
    :param ind:
    :return:
    Args:
        path_im: path to image
        ind: index of the slice around which we will average

    Returns:
        array: an array containing the average image.

    """
    image = nib.load(path_im)
    image = nib.as_closest_canonical(image)
    arr = np.array(image.dataobj)
    numb_of_slice = 3
    if ind + 3 < arr.shape[0] :
        numb_of_slice = arr.shape[0]-ind
    if ind - numb_of_slice < 0:
        numb_of_slice = ind

    return np.mean(arr[ind - numb_of_slice:ind + numb_of_slice, :, :], 0)


def images_normalization(img_list, std=True):
    if type(img_list) != list:
        img_list = [img_list]
    img_norm_list = []
    for i in range(len(img_list)):
        # print('Normalizing ' + str(i + 1) + '/' + str(len(img_list)))
        img = img_list[i] - np.mean(img_list[i])  # zero-center
        if std:
            img_std = np.std(img)  # normalize
            epsilon = 1e-100
            img = img / (img_std + epsilon)  # epsilon is used in order to avoid by zero division
        img_norm_list.append(img)
    return img_norm_list


def extract_all(list_coord_label, shape_im=(1, 150, 200)):
    """
    Create groundtruth by creating gaussian Function for every ground truth points for a single image
    Args:
        list_coord_label(list): list of ground truth coordinates
        shape_im (tuple): shape of output image with zero padding
    Returns:
         2D-array: a 2d heatmap image.
    """
    shape_tmp = (1, shape_im[0], shape_im[1])
    final = np.zeros(shape_tmp)
    for x in list_coord_label:
        train_lbs_tmp_mask = label2maskmap_gt(x, shape_tmp)
        for w in range(shape_im[0]):
            for h in range(shape_im[1]):
                final[0, w, h] = max(final[0, w, h], train_lbs_tmp_mask[w, h])
    return final


def extract_mid_slice_and_convert_coordinates_to_heatmaps(bids_path, suffix, aim):
    """
     This function takes as input a path to a dataset and generate two sets of images:
   (i) mid-sagittal image and
   (ii) heatmap of disc labels associated with the mid-sagittal image.

    Args:
        bids_path (string): path to BIDS dataset form which images will be generated
        suffix (string): suffix of image that will be processed (e.g., T2w)
        aim(string): 'full' or 'c2'. If 'c2' retrieves only c2 label (value = 3) else create heatmap with all label.

    Returns:
        None. Image are saved in Bids folder
    """
    t = os.listdir(bids_path)
    print(t)
    t.remove('derivatives')
    print(t)

    for i in range(len(t)):
        sub = t[i]
        path_image = bids_path + t[i] + '/anat/' + t[i] + suffix + '.nii.gz'
        if os.path.isfile(path_image):
            path_label = bids_path + 'derivatives/labels/' + t[i] + '/anat/' + t[i] + suffix + '_labels-disc-manual.nii.gz'
            list_points = mask2label(path_label, aim=aim)
            image_ref = nib.load(path_image)
            nib_ref_can = nib.as_closest_canonical(image_ref)
            imsh = np.array(image_ref.dataobj).shape
            mid = get_midslice_average(path_image, list_points[0][0])
            arr_pred_ref_space = imad_utils.reorient_image(np.expand_dims(np.flip(mid[:, :], axis=1), axis=0), 2, image_ref, nib_ref_can).astype('float32')
            nib_pred = nib.Nifti1Image(arr_pred_ref_space, image_ref.affine)
            nib.save(nib_pred, bids_path + t[i] + '/anat/' + t[i] + suffix + '_mid.nii.gz')
            lab = nib.load(path_label)
            nib_ref_can = nib.as_closest_canonical(lab)
            label_array = np.zeros(imsh[1:])

            if aim == 'c2':
                for j in range (len (list_points[0])):
                    if label_array[list_points[1][j],list_points[0][j]]==3:
                        label_array[list_points[1][j], list_points[0][j]] = 1
            elif aim == 'full':
                for j in range(len(list_points[0])):
                    label_array[list_points[1][j], list_points[0][j]] = 1

            heatmap = heatmap_generation(label_array[list_points[0][0], :, :], 10)
            arr_pred_ref_space = imed_utils.reorient_image(np.expand_dims(np.flip(heatmap[:, :], axis=1), axis=0), 2, lab, nib_ref_can)
            nib_pred = nib.Nifti1Image(arr_pred_ref_space, image_ref.affine)
            nib.save(nib_pred, bids_path + 'derivatives/labels/' + t[i] + '/anat/' + t[i] + suffix + 'heatmap.nii.gz')
        else:
            pass
        





