import taichi_lang as ti
import numpy as np
import random
import cv2

real = ti.f32
dim = 2
n_particles = 8192 * 4
n_grid = 256
dx = 1 / n_grid
inv_dx = 1 / dx
dt = 1e-4
p_mass = 1
p_vol = 1
E = 100
steps = 1024
gravity = 9.8

scalar = lambda: ti.var(dt=real)
vec = lambda: ti.Vector(dim, dt=real)
mat = lambda: ti.Matrix(dim, dim, dt=real)
f = ti.var(ti.i32)

x, v = vec(), vec()
grid_v_in, grid_m_in = vec(), scalar()
grid_v_out = vec()
C, J = mat(), scalar()

# ti.cfg.arch = ti.x86_64
ti.cfg.arch = ti.cuda

@ti.layout
def place():
  ti.root.dense(ti.l, steps).dense(ti.k, n_particles).place(x, v, J, C)
  ti.root.dense(ti.ij, n_grid).place(grid_v_in, grid_m_in, grid_v_out)
  ti.root.place(f)


@ti.kernel
def clear_grid():
  for i, j in grid_m_in:
    grid_v_in[i, j] = [0, 0]
    grid_m_in[i, j] = 0

@ti.kernel
def inc_f():
  global f
  f += 1

@ti.kernel
def dec_f():
  global f
  f -= 1

@ti.kernel
def p2g():
  for p in range(0, n_particles):
    base = ti.cast(x[f, p] * inv_dx - 0.5, ti.i32)
    fx = x[f, p] * inv_dx - ti.cast(base, ti.f32)
    w = [0.5 * ti.sqr(1.5 - fx), 0.75 - ti.sqr(fx - 1),
         0.5 * ti.sqr(fx - 0.5)]
    stress = -dt * p_vol * (J[f, p] - 1) * 4 * inv_dx * inv_dx * E
    affine = ti.Matrix([[stress, 0], [0, stress]]) + p_mass * C[f, p]
    for i in ti.static(range(3)):
      for j in ti.static(range(3)):
        offset = ti.Vector([i, j])
        dpos = (ti.cast(ti.Vector([i, j]), ti.f32) - fx) * dx
        weight = w[i](0) * w[j](1)
        grid_v_in[base + offset].atomic_add(weight * (p_mass * v[f, p] + affine @ dpos))
        grid_m_in[base + offset].atomic_add(weight * p_mass)


bound = 3


@ti.kernel
def grid_op():
  for i, j in grid_m_in:
    if grid_m_in[i, j] > 0:
      inv_m = 1 / grid_m_in[i, j]

      grid_v_out[i, j] = inv_m * grid_v_in[i, j]

      grid_v_out(1)[i, j] -= dt * gravity

      if i < bound and grid_v_out(0)[i, j] < 0:
        grid_v_out(0)[i, j] = 0
      if i > n_grid - bound and grid_v_out(0)[i, j] > 0:
        grid_v_out(0)[i, j] = 0
      if j < bound and grid_v_out(1)[i, j] < 0:
        grid_v_out(1)[i, j] = 0
      if j > n_grid - bound and grid_v_out(1)[i, j] > 0:
        grid_v_out(1)[i, j] = 0
    else:
      grid_v_out[i, j] = ti.Vector([0, 0])


@ti.kernel
def g2p():
  for p in range(0, n_particles):
    base = ti.cast(x[f, p] * inv_dx - 0.5, ti.i32)
    fx = x[f, p] * inv_dx - ti.cast(base, ti.f32)
    w = [0.5 * ti.sqr(1.5 - fx), 0.75 - ti.sqr(fx - 1.0),
         0.5 * ti.sqr(fx - 0.5)]
    new_v = ti.Vector([0.0, 0.0])
    new_C = ti.Matrix([[0.0, 0.0], [0.0, 0.0]])

    for i in ti.static(range(3)):
      for j in ti.static(range(3)):
        dpos = ti.cast(ti.Vector([i, j]), ti.f32) - fx
        g_v = grid_v_out[base(0) + i, base(1) + j]
        weight = w[i](0) * w[j](1)
        new_v += weight * g_v
        new_C += 4 * weight * ti.outer_product(g_v, dpos) * inv_dx

    v[f + 1, p] = new_v
    x[f + 1, p] = x[f, p] + dt * v[f + 1, p]
    J[f + 1, p] = J[f, p] * (1 + dt * new_C.trace())
    C[f + 1, p] = new_C


def main():
  for i in range(n_particles):
    x[0, i] = [random.random() * 0.4 + 0.2, random.random() * 0.4 + 0.1]
    v[0, i] = [0, -10]
    J[0, i] = 1

  for s in range(steps - 1):
    clear_grid()
    p2g()
    grid_op()
    g2p()
    inc_f()

  dec_f()
  g2p.grad()
  p2g.grad()

  ti.profiler_print()

  while True:
    for s in range(0, steps - 1, 16):
      scale = 2
      img = np.zeros(shape=(scale * n_grid, scale * n_grid)) + 0.3
      for i in range(n_particles):
        p_x = int(scale * x(0)[s, i] / dx)
        p_y = int(scale * x(1)[s, i] / dx)
        img[p_x, p_y] = 1
      img = img.swapaxes(0, 1)[::-1]
      cv2.imshow('MPM', img)
      cv2.waitKey(1)

if __name__ == '__main__':
  main()
