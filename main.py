import pygame
import math

pygame.init()

WIDTH, HEIGHT = 1920, 1080
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Soccer Game")

clock = pygame.time.Clock()

# Colors
FIELD_GREEN = (40, 160, 60)
WHITE = (255, 255, 255)
ORANGE = (255, 140, 0)

font = pygame.font.SysFont(None, 120)
count_font = pygame.font.SysFont(None, 100)

# Player
player_radius = 20
player_x = WIDTH // 4
player_y = HEIGHT // 2

BASE_SPEED = 5
SPRINT_SPEED = 7
player_speed = BASE_SPEED

face_x = 1
face_y = 0

# Ball
ball_x = WIDTH // 2
ball_y = HEIGHT // 2
ball_radius = 12

ball_vx = 0
ball_vy = 0

FRICTION = 0.98

# Kick
MAX_KICK_POWER = 25
KICK_CHARGE_RATE = 0.5

kick_power = 0
kick_cooldown = 0
KICK_COOLDOWN_TIME = 20

holding_ball = False

# Goals
GOAL_WIDTH = 40
GOAL_HEIGHT = 250

# Game state
game_state = "playing"
goal_timer = 0
countdown_timer = 0


def reset_positions():
    global player_x, player_y
    global ball_x, ball_y
    global ball_vx, ball_vy
    global holding_ball

    player_x = WIDTH // 4
    player_y = HEIGHT // 2

    ball_x = WIDTH // 2
    ball_y = HEIGHT // 2

    ball_vx = 0
    ball_vy = 0

    holding_ball = False


def draw_field():
    screen.fill(FIELD_GREEN)

    pygame.draw.rect(
        screen,
        WHITE,
        (0, 0, WIDTH, HEIGHT),
        5
    )

    pygame.draw.line(
        screen,
        WHITE,
        (WIDTH // 2, 0),
        (WIDTH // 2, HEIGHT),
        5
    )

    pygame.draw.circle(
        screen,
        WHITE,
        (WIDTH // 2, HEIGHT // 2),
        120,
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (0, HEIGHT // 2 - 200, 250, 400),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (WIDTH - 250, HEIGHT // 2 - 200, 250, 400),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (0, HEIGHT // 2 - GOAL_HEIGHT // 2, GOAL_WIDTH, GOAL_HEIGHT),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (WIDTH - GOAL_WIDTH, HEIGHT // 2 - GOAL_HEIGHT // 2, GOAL_WIDTH, GOAL_HEIGHT),
        5
    )


def score_goal():
    global game_state
    global goal_timer

    game_state = "goal"
    goal_timer = 180

    reset_positions()

running = True

while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()

    if kick_cooldown > 0:
        kick_cooldown -= 1

    if game_state == "playing":

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

        if dx != 0 or dy != 0:
            length = math.hypot(dx, dy)
            dx /= length
            dy /= length

            face_x = dx
            face_y = dy

        if holding_ball:
            speed_multiplier = 0.8
        else:
            speed_multiplier = 1

        if keys[pygame.K_LSHIFT]:
            player_speed = SPRINT_SPEED * speed_multiplier
        else:
            player_speed = BASE_SPEED * speed_multiplier

        if keys[pygame.K_SPACE] and holding_ball and kick_cooldown == 0:
            kick_power += KICK_CHARGE_RATE

            if kick_power > MAX_KICK_POWER:
                kick_power = MAX_KICK_POWER

        if not keys[pygame.K_SPACE] and kick_power > 0 and holding_ball:
            holding_ball = False

            ball_vx = face_x * kick_power
            ball_vy = face_y * kick_power

            kick_power = 0
            kick_cooldown = KICK_COOLDOWN_TIME

        player_x += dx * player_speed
        player_y += dy * player_speed

        player_x = max(player_radius, min(WIDTH - player_radius, player_x))
        player_y = max(player_radius, min(HEIGHT - player_radius, player_y))

        if not holding_ball and kick_cooldown == 0:
            distance = math.hypot(ball_x - player_x, ball_y - player_y)

            if distance < player_radius + ball_radius:
                holding_ball = True
                ball_vx = 0
                ball_vy = 0

        if holding_ball:
            ball_x = player_x + face_x * (player_radius + ball_radius + 5)
            ball_y = player_y + face_y * (player_radius + ball_radius + 5)

        else:
            ball_x += ball_vx
            ball_y += ball_vy

            ball_vx *= FRICTION
            ball_vy *= FRICTION

            if abs(ball_vx) < 0.05:
                ball_vx = 0

            if abs(ball_vy) < 0.05:
                ball_vy = 0

        if ball_x < GOAL_WIDTH:
            if abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2:
                game_state = "goal"
                goal_timer = 180
                reset_positions()

        if ball_x > WIDTH - GOAL_WIDTH:
            if abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2:
                game_state = "goal"
                goal_timer = 180
                reset_positions()

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

    elif game_state == "goal":

        goal_timer -= 1

        if goal_timer <= 0:
            game_state = "countdown"
            countdown_timer = 300

    elif game_state == "countdown":

        countdown_timer -= 1

        if countdown_timer <= 0:
            game_state = "playing"

    draw_field()

    pygame.draw.circle(
        screen,
        (50, 200, 255),
        (int(player_x), int(player_y)),
        player_radius
    )

    pygame.draw.circle(
        screen,
        ORANGE,
        (int(ball_x), int(ball_y)),
        ball_radius
    )

    if holding_ball:
        bar_width = 60
        bar_height = 8

        bar_x = player_x - bar_width / 2
        bar_y = player_y + player_radius + 10

        pygame.draw.rect(
            screen,
            (50, 50, 50),
            (bar_x, bar_y, bar_width, bar_height)
        )

        power_ratio = kick_power / MAX_KICK_POWER
        power_ratio = min(power_ratio, 1)

        if power_ratio < 0.5:
            r = int(255 * power_ratio * 2)
            g = 255
        else:
            r = 255
            g = int(255 * (1 - (power_ratio - 0.5) * 2))

        pygame.draw.rect(
            screen,
            (r, g, 0),
            (bar_x, bar_y, bar_width * power_ratio, bar_height)
        )

    if game_state == "goal":
        text = font.render("GOAL!", True, WHITE)

        screen.blit(
            text,
            (
                WIDTH // 2 - text.get_width() // 2,
                HEIGHT // 2 - text.get_height() // 2
            )
        )

    if game_state == "countdown":
        seconds = math.ceil(countdown_timer / 60)

        text = count_font.render(str(seconds), True, WHITE)

        screen.blit(
            text,
            (
                WIDTH // 2 - text.get_width() // 2,
                HEIGHT // 2 - text.get_height() // 2
            )
        )

    pygame.display.flip()

pygame.quit()