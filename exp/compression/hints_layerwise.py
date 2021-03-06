import math
import random
import os, sys, getopt
import cPickle as pkl

from pylearn2.config import yaml_parse
from pylearn2 import train
from pylearn2.models.mlp import Sigmoid, Tanh, Softmax, RectifiedLinear, ConvRectifiedLinear, RectifierConvNonlinearity, SigmoidConvNonlinearity, TanhConvNonlinearity
from pylearn2.models.maxout import MaxoutConvC01B, Maxout
from pylearn2.models.mlp import ConvElemwise as ConvElemwisePL2
from pylearn2.space import VectorSpace
from pylearn2.costs.cost import MethodCost
from pylearn2.train_extensions.best_params import MonitorBasedSaveBest

from models.layer.convVariable import ConvElemwise
from models.layer.SoftmaxBC01Extended import SoftmaxExtended
from models.layer.SigmoidBC01Extended import SigmoidExtended
from models.layer.cudnnVariable import CudNNElemwise
from utils.compression.TeacherHintRegressionCost import TeacherHintRegressionCost
from utils.compression.TeacherDecayOverEpoch import TeacherDecayOverEpoch

def generateConvRegressor(teacher_hintlayer, student_layer):
  
  layer_name = 'hint_regressor'
  out_ch = teacher_hintlayer.get_output_space().num_channels
  ks0 = student_layer.get_output_space().shape[0] - teacher_hintlayer.get_output_space().shape[0] + 1
  ks1 = student_layer.get_output_space().shape[1] - teacher_hintlayer.get_output_space().shape[1] + 1
  ks = [ks0, ks1]
  irng = 0.05
  mkn = 0.9
  tb = 1  
        
  if isinstance(teacher_hintlayer, MaxoutConvC01B):
    hint_reg_layer = MaxoutConvC01B(num_channels=out_ch, 
				    num_pieces=teacher_hintlayer.num_pieces, 
				    kernel_shape=ks, 
				    pool_shape=[1,1], 
				    pool_stride=[1,1], 
				    layer_name=layer_name, 
				    irange=irng,  
				    max_kernel_norm=mkn, 
				    tied_b=teacher_hintlayer.tied_b)

  elif isinstance(teacher_hintlayer, ConvRectifiedLinear):
    nonlin = RectifierConvNonlinearity()
    hint_reg_layer = ConvElemwise(output_channels = out_ch,
				  kernel_shape = ks,
				  layer_name = layer_name,
				  nonlinearity = nonlin,
				  irange = irng,
				  max_kernel_norm = mkn,
				  tied_b = tb)
				  
  elif isinstance(teacher_hintlayer, ConvElemwise):
    nonlin = teacher_hintlayer.nonlinearity
    
    #if isinstance(nonlin,TanhConvNonlinearity):
    #  nonlin = SigmoidConvNonlinearity()
      
    hint_reg_layer = ConvElemwise(output_channels = out_ch,
				  kernel_shape = ks,
				  layer_name = layer_name,
				  nonlinearity = nonlin,
				  irange = irng,
				  max_kernel_norm = mkn,
				  tied_b = tb)   
  elif isinstance(teacher_hintlayer, ConvElemwisePL2):
    nonlin = teacher_hintlayer.nonlinearity
    
    #if isinstance(nonlin,TanhConvNonlinearity):
    #  nonlin = SigmoidConvNonlinearity()
      
    hint_reg_layer = ConvElemwisePL2(output_channels = out_ch,
				  kernel_shape = ks,
				  layer_name = layer_name,
				  nonlinearity = nonlin,
				  irange = irng,
				  max_kernel_norm = mkn,
				  tied_b = tb) 
  elif isinstance(teacher_hintlayer, CudNNElemwise):
    nonlin = teacher_hintlayer.nonlinearity
    
    #if isinstance(nonlin,TanhConvNonlinearity):
    #  nonlin = SigmoidConvNonlinearity()
      
    hint_reg_layer = CudNNElemwise(output_channels = out_ch,
				  kernel_shape = ks,
				  layer_name = layer_name,
				  nonlinearity = nonlin,
				  irange = irng,
				  max_kernel_norm = mkn,
				  tied_b = tb) 
  else:
    raise AssertionError("Unknown layer type")
    
  return hint_reg_layer
     
def generateNonConvRegressor(teacher_hintlayer, student_output_space):
  dim = teacher_hintlayer.output_space.get_total_dimension()
  layer_name = 'hint_regressor'
  
  irng = 0.05
  mcn = 0.9
    
  if isinstance(teacher_hintlayer, MaxoutConvC01B):
    hint_reg_layer = Maxout(layer_name, dim, teacher_hintlayer.num_pieces, irange=irng, max_col_norm= mcn)
  elif isinstance(teacher_hintlayer, ConvRectifiedLinear):
    hint_reg_layer = RectifiedLinear(dim=dim, layer_name=layer_name, irange=irng, max_col_norm= mcn)
  elif isinstance(teacher_hintlayer, ConvElemwise) or isinstance(teacher_hintlayer, ConvElemwisePL2):
    if isinstance(teacher_hintlayer.nonlinearity,RectifierConvNonlinearity):
      hint_reg_layer = RectifiedLinear(dim=dim, layer_name=layer_name, irange=irng, max_col_norm= mcn)
    elif isinstance(teacher_hintlayer.nonlinearity,SigmoidConvNonlinearity):
      hint_reg_layer = Sigmoid(dim=dim, layer_name=layer_name, irange=irng, max_col_norm= mcn)
    elif isinstance(teacher_hintlayer.nonlinearity,TanhConvNonlinearity):
      hint_reg_layer = Tanh(dim=dim, layer_name=layer_name, irange=irng, max_col_norm= mcn)
    else:
      raise AssertionError("Unknown layer type")
  else:
      raise AssertionError("Unknown layer type")
  
  return hint_reg_layer
      
def splitStudentNetwork(student, fromto_student, teacher, hintlayer, regressor_type):

  # Check if we are in the softmax layers
  if isinstance(teacher.layers[hintlayer], Softmax) or isinstance(teacher.layers[hintlayer], SoftmaxExtended) or isinstance(teacher.layers[hintlayer], SigmoidExtended):
    assert (isinstance(student.model.layers[fromto_student[1]], Softmax) or isinstance(student.model.layers[fromto_student[1]], SoftmaxExtended) or isinstance(student.model.layers[fromto_student[1]], SigmoidExtended))
    assert teacher.layers[hintlayer].get_output_space().dim == student.model.layers[fromto_student[1]].get_output_space().dim
    
  else:
    # Retrieve student subnetwork
    if fromto_student[1] < len(student.model.layers)-1:
      del student.model.layers[fromto_student[1]+1:] 
        
    teacher_output_space = teacher.layers[hintlayer].get_output_space()
    student_output_space = student.model.layers[fromto_student[1]].get_output_space()  
        
    # Add regressor to the student subnetwork if needed
    if regressor_type == 'conv':
      if(teacher_output_space.shape < student_output_space.shape or (teacher_output_space.num_channels > student_output_space.num_channels and teacher_output_space.shape == student_output_space.shape)):
	# Add convolutional regressor
	hint_reg_layer = generateConvRegressor(teacher.layers[hintlayer], student.model.layers[-1])
	hint_reg_layer.set_mlp(student.model)  
	hint_reg_layer.set_input_space(student.model.layers[-1].output_space)
	student.model.layers.append(hint_reg_layer)
      elif (teacher_output_space.shape == student_output_space.shape and teacher_output_space.num_channels == student_output_space.num_channels):
	pass
    elif regressor_type == 'fc':
      raise NotImplementedError('FC')
      # Add fully-connected regressor
      hint_reg_layer = generateNonConvRegressor(teacher.layers[hintlayer], student_output_space)
      hint_reg_layer.set_mlp(student.model)  
      hint_reg_layer.set_input_space(student.model.layers[-1].output_space)
      student.model.layers.append(hint_reg_layer)
    else:
      raise AssertionError("Unknown regressor type")

    # Change cost to optimize wrt teacher hints
    student.algorithm.cost = TeacherHintRegressionCost(teacher,hintlayer)
    
    # Set monitor_targets to false
    student.model.monitor_targets = False

    # Change monitored channel
    if student.algorithm.monitoring_dataset.has_key('valid'):
      student.algorithm.termination_criterion.channel_name = "valid_cost_wrt_teacher"
      student.algorithm.termination_criterion._channel_name = "valid_cost_wrt_teacher"
      
      # Change monitoring channel for best model    
      for ext in range(len(student.extensions)):
	if isinstance(student.extensions[ext],MonitorBasedSaveBest):
	  student.extensions[ext].channel_name = "valid_cost_wrt_teacher"
    elif student.algorithm.monitoring_dataset.has_key('test'):
      student.algorithm.termination_criterion.channel_name = "test_cost_wrt_teacher"
      student.algorithm.termination_criterion._channel_name = "test_cost_wrt_teacher"
    
      # Change monitoring channel for best model    
      for ext in range(len(student.extensions)):
	if isinstance(student.extensions[ext],MonitorBasedSaveBest):
	  student.extensions[ext].channel_name = "test_cost_wrt_teacher"
	  
    else:
      raise AssertionError("Unknown monitoring dataset")
    
  # Remove teacher decay over epoch if there is one
  for ext in range(len(student.extensions)):
    if isinstance(student.extensions[ext],TeacherDecayOverEpoch):
      del student.extensions[ext]
      
  # Change save path
  for ext in range(len(student.extensions)):
    if isinstance(student.extensions[ext],MonitorBasedSaveBest):
      student.extensions[ext].save_path = student.save_path[0:-4] + "_hintlayer" + str(fromto_student[1]) + "_best.pkl"
  student.save_path = student.save_path[0:-4] + "_hintlayer" + str(fromto_student[1]) + ".pkl"
    
  # Freeze parameters of the layers trained in the last subnetworks
  #for i in range(0,fromto_student[0]):
  #  student.model.freeze(student.model.layers[i].get_params())

  return student
    
def main(argv):
  
  try:
    opts, args = getopt.getopt(argv, '')
    student_yaml = args[0]
    regressor_type = args[1]
  except getopt.GetoptError:
    usage()
    sys.exit(2) 
    

  # Load student
  with open(student_yaml, "r") as sty:
    student = yaml_parse.load(sty)
    
  # Load teacher network
  teacher = student.algorithm.cost.teacher
    
  # Load hints and check whether they are within the proper range
  if student.algorithm.cost.hints is not None:
    student_layers = list(zip(*student.algorithm.cost.hints)[0]) 
    teacher_layers = list(zip(*student.algorithm.cost.hints)[1])
     
    assert len(student_layers) == len(teacher_layers)
    n_hints = len(student_layers)

    assert max(student_layers) <= len(student.model.layers)-2
    if isinstance(teacher.layers[-1], SoftmaxExtended):
      assert max(teacher_layers) <= len(teacher.layers)-3
    else:
      assert max(teacher_layers) <= len(teacher.layers)-2
  else:
    n_hints = 0
  
  # Train layers with teacher hints 
  for i in range(n_hints):
    print 'Training student hint layer %d out of %d' % (i+1, n_hints)
      
    # Select student block of layers forming subnetwork
    bottom_layer = student_layers[i-1]+1 if i>0 else 0
    top_layer = student_layers[i]
  
    # Load auxiliary copies of the student and the teacher to be able to modify them
    with open(student_yaml, "r") as sty:
      student_aux = yaml_parse.load(sty)
    teacher_aux = student_aux.algorithm.cost.teacher
    
    # Retrieve student subnetwork and add regression to teacher layer
    student_hint = splitStudentNetwork(student_aux, [bottom_layer, top_layer], teacher_aux, teacher_layers[i],regressor_type)
    
    # Train student subnetwork
    student_hint.main_loop()
    
    # Load best model
    best_path = student_hint.save_path
    for ext in range(len(student_hint.extensions)):
      if isinstance(student_hint.extensions[ext],MonitorBasedSaveBest):
	best_path = student_hint.extensions[ext].save_path
	
    fo = open(best_path, 'r')
    best_pretrained_model = pkl.load(fo)
    fo.close()
          
    # Save pretrained student subnetworks together (without regression to teacher layer)
    student.model.layers[0:top_layer+1] = best_pretrained_model.layers[0:top_layer+1]

  print 'Training student softmax layer'
  import pdb
  pdb.set_trace()
  # Train softmax layer and stack it to the pretrained student network
  softmax_hint = splitStudentNetwork(student, [0, len(student.model.layers)-1], teacher, len(teacher.layers)-1,regressor_type) 
  softmax_hint.main_loop()
  
  # Load best model
  best_path = softmax_hint.save_path
  for ext in range(len(softmax_hint.extensions)):
    if isinstance(softmax_hint.extensions[ext],MonitorBasedSaveBest):
      best_path = softmax_hint.extensions[ext].save_path
	
  fo = open(best_path, 'r')
  best_pretrained_model = pkl.load(fo)
  fo.close()
          
  student.model.layers = best_pretrained_model.layers
    
  #print 'Finetuning student network'
      
  ## Remove previous monitoring to be able to finetune the student network
  #assert hasattr(student.model,'monitor')
  #old_monitor = student.model.monitor
  #setattr(student.model, 'lastlayer_monitor', old_monitor)
  #del student.model.monitor
  
  ## Change cost
  #student.algorithm.cost = MethodCost(method='cost_from_X')

  ## Change save paths
  #student.save_path = student.save_path[0:-4] + "_finetuned.pkl"
  #for ext in range(len(student.extensions)):
    #if isinstance(student.extensions[ext],MonitorBasedSaveBest):
      #student.extensions[ext].save_path = student.save_path[0:-4] + "_best.pkl" 
  
  ##Finetune student network
  #student.main_loop()
  
if __name__ == "__main__":
  main(sys.argv[1:])
