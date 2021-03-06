# -*- coding: utf-8 -*-
# @Time    : 2018/7/31 09:41
# @Author  : Spytensor
# @File    : main.py
# @Email   : zhuchaojie@buaa.edu.cn
#====================================================
#               定义模型训练/验证/预测等                     
#====================================================
from torch.optim import lr_scheduler
from torch.autograd import Variable
from torchnet import meter
from config import config
from data_loader import cloth_data
from torchvision import transforms as T
from utils import AverageMeter,accuracy
from tqdm import tqdm
from model import get_net
import torchvision
import torch
import time
import os
import warnings
import json
warnings.filterwarnings("ignore")
os.environ["CUDA_VISIBLE_DEVICES"] = config.gpu

#1.训练
def train(train_loader, model, criterion, optimizer, scheduler,epoch):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    acc = AverageMeter()
    # switch to train mode
    if os.path.exists(config.weights_path):
        model.load_state_dict(torch.load(config.weights_path))
    model.train()
    end = time.time()
    scheduler.step()
    for i, (images, target) in enumerate(tqdm(train_loader)):
        # measure data loading time
        data_time.update(time.time() - end)
        target = target.cuda(async=True)
        image_var = torch.autograd.Variable(images).cuda()
        label_var = torch.autograd.Variable(target).cuda()
        # compute y_pred
        if config.model_name == "inception_v3":
            y_pred,aux = model(image_var)
        else:
            y_pred = model(image_var)
        loss = criterion(y_pred, label_var)
        # measure accuracy and record loss
        prec1, prec1 = accuracy(y_pred.data, target, topk=(1, 1))
        losses.update(loss.data[0], images.size(0))
        acc.update(prec1[0], images.size(0))
        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()
        if i % config.print_freq == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Accuracy [val: {acc.val:.3f}  avg: {acc.avg:.3f}]'.format(
                      epoch, i, len(train_loader), loss=losses, acc=acc))
#2.验证
def val(val_loader, model, criterion):
    print("validating...")
    batch_time = AverageMeter()
    losses = AverageMeter()
    acc = AverageMeter()
    # switch to evaluate mode
    model.eval()
    end = time.time()
    for i, (images, labels) in enumerate(val_loader):
        labels = labels.cuda(async=True)
        image_var = torch.autograd.Variable(images, volatile=True).cuda()
        label_var = torch.autograd.Variable(labels, volatile=True).cuda()
        # compute y_pred
        y_pred = model(image_var)
        loss = criterion(y_pred, label_var)
        # measure accuracy and record loss
        prec1, temp_var = accuracy(y_pred.data, labels, topk=(1, 1))
        losses.update(loss.data[0], images.size(0))
        acc.update(prec1[0], images.size(0))
        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()
        if i % config.print_freq == 0:
            print('TrainVal: [{0}/{1}]\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Accuracy [val: {acc.val:.3f}  avg: {acc.avg:.3f}]'.format(
                      i, len(val_loader), loss=losses, acc=acc))
    print(' * Accuracy {acc.avg:.3f}'.format(acc=acc))
    return acc.avg
#3.测试
def test(test_loader,model):
    model.load_state_dict(torch.load(config.weights_path))
    results = []
    with open("./results/re.json","w",encoding="utf-8") as f:
        iii = 0
        for i,(images,file_paths) in enumerate(tqdm(test_loader)):
            image_var = torch.autograd.Variable(images).cuda()
            y_pred = model(image_var)            
            for file_path,index in zip(file_paths,torch.nn.functional.softmax(y_pred)):
                image_id = file_path.split("/")[-1]
                disease_class = index.cpu().data.numpy().argmax()
                results.append({"image_id":image_id,"disease_class":str(disease_class)})
        json.dump(results,f,ensure_ascii=False)
if __name__ == "__main__":
    #1.搭建模型
    model = torchvision.models.resnet152(pretrained=True)
    for param in model.parameters():
        param.requires_grad = False
    model.fc = torch.nn.Linear(model.fc.in_features,config.num_classes)
    model.cuda()
    mode = "train"   
    #1.2定义评判标准和优化器
    optimizer = torch.optim.Adam(model.parameters(),lr=config.lr)
    exp_lr_scheduler = lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)
    criterion = torch.nn.CrossEntropyLoss().cuda()
    #1.3数据增强方式
    transforms_train = T.Compose([
        T.Resize((config.img_size,config.img_size)),
        T.RandomRotation(90),
        T.RandomHorizontalFlip(),
        T.RandomVerticalFlip(),
        T.RandomAffine(45),
        T.ToTensor(),
        T.Normalize(mean = [0.485,0.456,0.406],
                    std = [0.229,0.224,0.225]),

    ])
    transforms_val_test = T.Compose([
        T.Resize((config.img_size,config.img_size)),
        T.ToTensor(),
        T.Normalize(mean = [0.485,0.456,0.406],
                    std = [0.229,0.224,0.225]),

    ])
    if mode == "train":
        #2.构建数据载入
        train_data = cloth_data(config.data_path,transforms=transforms_train)
        val_data = cloth_data(config.data_path,train=False,transforms=transforms_val_test)
        train_dataloader = torch.utils.data.DataLoader(train_data,batch_size=config.batch_size,shuffle=True)
        val_dataloader = torch.utils.data.DataLoader(val_data,batch_size=config.batch_size,shuffle=True)

        #3.开启训练
        best_prec1 = 0
        for epoch in range(config.epochs):
            train(train_dataloader,model,criterion,optimizer,exp_lr_scheduler,epoch)
            prec1 = val(val_dataloader, model, criterion)
            is_best = prec1 > best_prec1
            raw_score = best_prec1
            best_prec1 = max(prec1, best_prec1)
            if is_best :
                try:
                    print("Get Better model,the accuracy has updated from : {} to :{}".format(raw_score.cpu().numpy(),best_prec1.cpu().numpy()))
                except:
                    print("Get Better model,the accuracy has updated from : {} to :{}".format(raw_score,best_prec1.cpu().numpy()))
                torch.save(model.state_dict(), config.weights_path)
            else:
                print("No improvement in model performance ! Best accuracy is :",best_prec1.cpu().numpy())  
    else:
        print("testing!")
        test_data = cloth_data(config.test_path,transforms=transforms_val_test,test=True)
        test_loader = torch.utils.data.DataLoader(test_data,batch_size=config.batch_size,shuffle=True)
        test(test_loader,model)
