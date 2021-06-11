"""
DDPG
"""

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam
from copy import deepcopy

from .model import (Actor, Critic)
from .memory import SequentialMemory
from .random_process import OUProcess


USE_CUDA = torch.cuda.is_available()

LR = 0.001
RMSIZE = 100000
WINDOW_LEN = 1
TAU = 0.01
OU_PSI = 0.15
OU_SIGMA = 0.2
BATCH_SIZE = 64
DISCOUNT = 0.99

loss = nn.MSELoss()


def hard_update(target, source):
    """
    copy paramerters' value from source to target
    """
    for target_param, param in zip(target.parameters(), source.parameters()):
        target_param.data.copy_(param.data)


def soft_update(target, source, tau):
    """
    Update target network with blended weights from target and source.
    """
    for target_param, param in zip(target.parameters(), source.parameters()):
        target_param.data.copy_(
            target.param.data * (1.0 - tau) + param.data * tau
        )

def to_numpy(var):
    """
    turn pytorch tensor to numpy array
    """
    return var.cpu().data.numpy() if USE_CUDA else var.data.numpy()

def to_tensor(ndarray, requires_grad=False, dtype=torch.float32):
    """ turn numpy array to pytorch tensor  """
    return torch.tensor(torch.from_numpy(ndarray=ndarray),
                        dtype=dtype, requires_grad=requires_grad)
        
class DDPG:
    def __init__(self, nb_states, nb_actions):
        self.nb_states = nb_states
        self.nb_actions = nb_actions

        self.actor = Actor(self.nb_states, self.nb_actions)
        self.actor_target = Actor(self.nb_states, self.nb_actions)
        self.actor_optim = Adam(self.actor.parameters(), lr=LR)

        self.critic = Critic(self.nb_states, self.nb_actions)
        self.critic_target = Critic(self.nb_states, self.nb_actions)
        self.critic_optim = Adam(self.critic.parameters(), lr=LR)

        hard_update(self.actor_target, self.actor)
        hard_update(self.critic_target, self.critic)

        self.batch_size = BATCH_SIZE
        self.discount = DISCOUNT
        self.tau = TAU
        self.ignore_step = 10000
        self.memory = SequentialMemory(limit=RMSIZE, window_length=WINDOW_LEN)
        self.random_process = OUProcess(size=self.nb_actions, theta=OU_PSI,
                                        mu=0.0, sigma=OU_SIGMA)

        self.is_training = True
        self.s_t = None
        self.a_t = None

        if USE_CUDA:
            self.cuda()


    def cuda(self):
        self.actor.cuda()
        self.actor_target.cuda()
        self.critic.cuda()
        self.critic_target.cuda()

    def observe(self, r_t, s_t1, done):
        if self.is_training:
            self.memory.append(self.s_t, self.a_t, r_t, done)
            self.s_t = s_t1

    def random_action(self):
        action = np.random.uniform(-1.0, 1.0, size=self.nb_actions)
        self.a_t = action
        return action

    def select_action(self, s_t):
        action = to_numpy(self.actor(to_tensor(np.array([s_t])))).squeeze(0)
        action += self.is_training * self.random_process.sample()
        self.a_t = action
        return action

    def reset(self, obs):
        self.s_t = obs
        self.random_process.reset_states()

    def load_weights(self, output):
        if output is None:
            return

        self.actor.load_state_dict(
            torch.load('{}/actor.pth'.format(output))
        )

        self.critic.load_state_dict(
            torch.load('{}/actor.pth'.format(output))
        )

    def save_model(self, output):
        torch.save(
            self.actor.state_dict(),
            '{}/actor.pth'.format(output)
        )
        torch.save(
            self.critic.state_dict(),
            '{}/critic.pth'.format(output)
        )

    def update_policy(self):
        state_batch, action_batch, reward_batch, next_state_batch, \
            terminal_batch = self.memory.sample_and_split(self.batch_size)

        next_q_values = self.critic_target([
            to_tensor(next_state_batch, requires_grad=False),
            self.actor_target(to_tensor(next_state_batch, requires_grad=False))
        ])

        target_q_batch = to_tensor(reward_batch) + \
            self.discount * \
            to_tensor(terminal_batch.astype(np.float32))*next_q_values


        q_batch = self.critic([to_tensor(state_batch), to_tensor(action_batch)])

        value_loss = loss(q_batch, target_q_batch)
        value_loss.backward()
        self.critic_optim.step()
        self.critic_optim.zero_grad()

        policy_loss = -self.critic([to_tensor(state_batch),
                                    self.actor(to_tensor(state_batch))])

        policy_loss = policy_loss.mean()
        policy_loss.backward()
        self.actor_optim.step()
        self.actor_optim.zero_grad()

        soft_update(self.actor_target, self.actor, self.tau)
        soft_update(self.critic_target, self.critic, self.tau)

    def train(self, num_iter, env, output, max_episode_length=None):
        step = 0
        episode = 0
        episode_steps = 0
        episode_reward = 0
        observation = None
        while step < num_iter:
            if observation is None:
                observation = deepcopy(env.reset())
                agent.reset(observation)

            action = agent.select_action(observation)

            observ2, reward, done, _ = env.step(action)
            observ2 = deepcopy(observ2)
            if max_episode_length and episode_steps >= max_episode_length - 1:
                done = True

            self.observe(reward, observ2, done)
            if step > self.ignore_step:
                self.update_policy()

            if step % int(num_iter/3) == 0:
                self.save_model(output)

            step += 1
            episode_steps += 1
            episode_reward += reward
            observation = deepcopy(observ2)

            if done:
                self.memory.append(
                    observation,
                    self.select_action(observation),
                    0.,
                    False
                )

                observation = None
                episode_reward = 0.0
                episode_steps = 0
                episode += 1
