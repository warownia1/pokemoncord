import sys

from models import database, Pokemon


def drop_tables():
    database.connect()
    try:
        database.drop_tables([Pokemon])
        database.commit()
    finally:
        database.close()


def create_tables():
    database.connect()
    try:
        database.create_tables([Pokemon])
        database.commit()
    finally:
        database.close()


if __name__ == '__main__':
    if sys.argv[1] == 'run':
        import bot
        bot.main()
    elif sys.argv[1] == 'createdb':
        create_tables()
    elif sys.argv[1] == 'dropdb':
        drop_tables()
    else:
        raise ValueError('Invalid argument %s' % sys.argv[1])
