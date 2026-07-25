import pygame
import math

pygame.init()

# Screen
WIDTH, HEIGHT = 1920, 1080
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Soccer Movement")

clock = pygame.time.Clock()

# Player
player_x = WIDTH / 2
player_y = HEIGHT / 2
player_radius = 20

BASE_SPEED = 5
SPRINT_SPEED = 7
player_speed = BASE_SPEED

# Direction player is facing
face_x = 1
face_y = 0

# Ball
ball_x = 200
ball_y = 200
ball_radius = 12

ball_vx = 0
ball_vy = 0

KICK_SPEED = 12
FRICTION = 0.98

holding_ball = False

# Prevent instant pickup after kicking
kick_cooldown = 0

running = True
while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Keyboard input
    keys = pygame.key.get_pressed()

    dx = 0
    dy = 0

    if keys[pygame.K_w]:
        dy -= 1
    if keys[pygame.K_s]:
        dy += 1
    if keys[pygame.K_a]:
        dx -= 1
    if keys[pygame.K_d]:
        dx += 1

    # Normalize movement + update facing
    if dx != 0 or dy != 0:
        length = math.hypot(dx, dy)
        dx /= length
        dy /= length

        face_x = dx
        face_y = dy

    # Sprint
    if keys[pygame.K_LSHIFT]:
        player_speed = SPRINT_SPEED
    else:
        player_speed = BASE_SPEED

    # Kick
    if keys[pygame.K_SPACE] and holding_ball and kick_cooldown == 0:
        holding_ball = False

        ball_vx = face_x * KICK_SPEED
        ball_vy = face_y * KICK_SPEED

        kick_cooldown = 20

    # Reduce kick cooldown
    if kick_cooldown > 0:
        kick_cooldown -= 1

    # Move player
    player_x += dx * player_speed
    player_y += dy * player_speed

    # Keep player on screen
    player_x = max(player_radius, min(WIDTH - player_radius, player_x))
    player_y = max(player_radius, min(HEIGHT - player_radius, player_y))

    # Pick up ball
    if not holding_ball and kick_cooldown == 0:
        distance = math.hypot(ball_x - player_x, ball_y - player_y)

        if distance < player_radius + ball_radius:
            holding_ball = True
            ball_vx = 0
            ball_vy = 0

    # Ball behavior
    if holding_ball:

        # Ball follows player
        ball_x = player_x + face_x * (player_radius + ball_radius + 5)
        ball_y = player_y + face_y * (player_radius + ball_radius + 5)

    else:

        # Ball physics
        ball_x += ball_vx
        ball_y += ball_vy

        ball_vx *= FRICTION
        ball_vy *= FRICTION

        # Stop tiny movements
        if abs(ball_vx) < 0.05:
            ball_vx = 0

        if abs(ball_vy) < 0.05:
            ball_vy = 0

        # Bounce walls
        if ball_x <= ball_radius:
            ball_x = ball_radius
            ball_vx *= -1

        if ball_x >= WIDTH - ball_radius:
            ball_x = WIDTH - ball_radius
            ball_vx *= -1

        if ball_y <= ball_radius:
            ball_y = ball_radius
            ball_vy *= -1

        if ball_y >= HEIGHT - ball_radius:
            ball_y = HEIGHT - ball_radius
            ball_vy *= -1

    # Draw
    screen.fill((30, 30, 30))

    # Player
    pygame.draw.circle(
        screen,
        (50, 200, 255),
        (int(player_x), int(player_y)),
        player_radius
    )

    # Ball
    pygame.draw.circle(
        screen,
        (255, 255, 255),
        (int(ball_x), int(ball_y)),
        ball_radius
    )


    pygame.display.flip()


pygame.quit()