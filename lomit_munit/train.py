"""
Copyright (C) 2018 NVIDIA Corporation.  All rights reserved.
Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode).
"""
import matplotlib.pyplot as plt
import matplotlib

from utils import get_all_data_loaders, prepare_sub_folder, write_html, write_loss, get_config, write_2images, Timer
import argparse
from torch.autograd import Variable
from trainer import MUNIT_Trainer, UNIT_Trainer
import torch.backends.cudnn as cudnn
import torch
import cv2
try:
    from itertools import izip as zip
except ImportError: # will be 3.x series
    pass
import os
import sys
import tensorboardX
import shutil
import datetime
import numpy as np
parser = argparse.ArgumentParser()
parser.add_argument('--config', type=str, default='configs/edges2handbags_folder.yaml', help='Path to the config file.')
parser.add_argument('--output_path', type=str, default='.', help="outputs path")
parser.add_argument("--resume", action="store_true")
parser.add_argument('--trainer', type=str, default='MUNIT', help="MUNIT|UNIT")
opts = parser.parse_args()

cudnn.benchmark = False

# Load experiment setting
config = get_config(opts.config)
max_iter = config['max_iter']
display_size = config['display_size']
config['vgg_model_path'] = opts.output_path

# Setup model and data loader
if opts.trainer == 'MUNIT':
    trainer = MUNIT_Trainer(config)
elif opts.trainer == 'UNIT':
    trainer = UNIT_Trainer(config)
else:
    sys.exit("Only support MUNIT|UNIT")
trainer.cuda()
train_loader_a, train_loader_b, test_loader_a, test_loader_b = get_all_data_loaders(config)
# print(train_loader_a.shape)
train_display_images_a = torch.stack([train_loader_a.dataset[i][0] for i in range(display_size)]).cuda()
train_display_images_b = torch.stack([train_loader_b.dataset[i][0] for i in range(display_size)]).cuda()
# print(train_display_images_b.min(), train_display_images_b.max(), train_display_images_b.shape)
# print(train_display_images_a.min(), train_display_images_a.max(), train_display_images_a.shape)

test_display_images_a = torch.stack([test_loader_a.dataset[i][0] for i in range(display_size)]).cuda()
test_display_images_b = torch.stack([test_loader_b.dataset[i][0] for i in range(display_size)]).cuda()

# Setup logger and output folders
model_name = os.path.splitext(os.path.basename(opts.config))[0]
train_writer = tensorboardX.SummaryWriter(os.path.join(opts.output_path + "/logs", model_name))
dtstr = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
output_directory = os.path.join(opts.output_path + "/outputs", model_name, dtstr)
checkpoint_directory, image_directory = prepare_sub_folder(output_directory)
shutil.copy(opts.config, os.path.join(output_directory, 'config.yaml')) # copy config file to output folder

# Start training
iterations = trainer.resume(checkpoint_directory, hyperparameters=config) if opts.resume else 0
while True:
    for it, (imageseg_a, imageseg_b) in enumerate(zip(train_loader_a, train_loader_b)):
        images_a = imageseg_a[0]
        disp_im_a = (images_a[0].transpose(0,1).transpose(1,2) + 1.)/2.
#         print(disp_im_a.shape)
        segs_a = imageseg_a[1]
        
#         plt.imshow(disp_im_a)
#         plt.savefig("LogImage/TESTA_" + str(it) + ".png")
        images_b = imageseg_b[0]
        segs_b = imageseg_b[1]
        h = segs_b[0].transpose(0,1).transpose(1,2)
        disp_im_b = (images_b[0].transpose(0,1).transpose(1,2) + 1.)/2.
        #z = disp_im_b*h
#         plt.imshow(h*1.)
#         plt.savefig("LogImage/TESTC_" + str(it) + ".png")
#         print(disp_im_b.shape)
#         print(disp_im_b.sum())
        if disp_im_b.sum() <= 1000:
            print("BLACK IMAGE")
            continue
#         plt.imshow(disp_im_b)
#         plt.savefig("LogImage/TESTB_" + str(it) + ".png")
        
        trainer.update_learning_rate()
        images_a, images_b = images_a.cuda().detach(), images_b.cuda().detach()
        segs_a, segs_b = segs_a.cuda().detach(), segs_b.cuda().detach()

        with Timer("Elapsed time in update: %f"):
            # Main training code
            trainer.dis_update(images_a, segs_a, images_b, segs_b, config)
            if 0 == it % 2:
                trainer.gen_update(images_a, segs_a, images_b, segs_b, config)
            torch.cuda.synchronize()

        # Dump training stats in log file
        if (iterations + 1) % config['log_iter'] == 0:
            print("Iteration: %08d/%08d" % (iterations + 1, max_iter))
            write_loss(iterations, trainer, train_writer)

        # Write images
        if ((iterations + 1) % config['image_save_iter'] == 0) or (iterations==24):
            with torch.no_grad():
                test_image_outputs = trainer.sample(test_loader_a, test_loader_b, display_size)
                train_image_outputs = trainer.sample(train_loader_a, train_loader_b, display_size)
            write_2images(test_image_outputs, display_size, image_directory, 'test_%08d' % (iterations + 1))
            write_2images(train_image_outputs, display_size, image_directory, 'train_%08d' % (iterations + 1))
            # HTML
            write_html(output_directory + "/index.html", iterations + 1, config['image_save_iter'], 'images')

        if ((iterations + 1) % config['image_display_iter'] == 0) or (iterations==24):
            with torch.no_grad():
                image_outputs = trainer.sample(test_loader_a, test_loader_b, display_size)
            write_2images(image_outputs, display_size, image_directory, 'train_current')

        # Save network weights
        if (iterations + 1) % config['snapshot_save_iter'] == 0:
            trainer.save(checkpoint_directory, iterations)

        iterations += 1
        if iterations >= max_iter:
            sys.exit('Finish training')

