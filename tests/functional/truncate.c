/*
 * Copyright (C) 2008  Google, Inc. All Rights Reserved.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, write to the Free Software Foundation, Inc.,
 * 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/xattr.h>
#include <fcntl.h>
#include <unistd.h>

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>

#include "testhelpers.h"

#define MAXLEN 256


const char *g_existing_filename = "%s/regular.file";
const char *g_new_filename = "%s/this.file.shouldnt.exist";

char g_existing_filepath[256];
char g_new_filepath[256];


int test_ftruncate_existing(void)
{
    int fd = open(g_existing_filepath, O_RDWR);
    int result = 0;
    int old_errno = errno;

    TEST_START();

    if (fd < 0) {
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to open %s in %s\n"
                           "Errno %d: %s\n",
                           g_existing_filepath, __func__,
                           old_errno, strerror(old_errno));
    }
    TEST_OK();

    result = ftruncate(fd, 0);
    if (result < 0) {
        old_errno = errno;
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to ftruncate %s in %s\n"
                           "Errno %d: %s\n",
                           g_existing_filepath, __func__,
                           old_errno, strerror(old_errno));

        close(fd);
    }
    TEST_OK();

    write(fd, "blah\n", strlen("blah\n"));
    close(fd);

    TEST_COMPLETE_OK();
}

int test_truncate_existing(void)
{
    int result = 0;
    int old_errno = errno;

    TEST_START();

    result = truncate(g_existing_filepath, 0);
    if (result < 0) {
        old_errno = errno;
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to truncate %s in %s\n"
                           "Errno %d: %s\n",
                           g_existing_filepath, __func__,
                           old_errno, strerror(old_errno));
    }
    TEST_OK();

    TEST_COMPLETE_OK();
}

int test_ftruncate_new_file(void)
{
    int fd = open(g_new_filepath, O_CREAT|O_RDWR, 0644);
    int result = 0;
    int old_errno = errno;

    TEST_START();

    if (fd < 0) {
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to open %s in %s\n"
                           "Errno %d: %s\n",
                           g_new_filepath, __func__,
                           old_errno, strerror(old_errno));
    }
    TEST_OK();

    result = ftruncate(fd, 0);
    if (result < 0) {
        old_errno = errno;
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to ftruncate %s in %s\n"
                           "Errno %d: %s\n",
                           g_new_filepath, __func__,
                           old_errno, strerror(old_errno));

        close(fd);
    }
    TEST_OK();

    close(fd);
    unlink(g_new_filepath);

    TEST_COMPLETE_OK();
}

int test_truncate_new_file(void)
{
    int result = 0;
    int old_errno = errno;

    TEST_START();

    result = truncate(g_new_filepath, 0);

    if (result == 0) {
        old_errno = errno;
        TEST_FAIL();
        TEST_COMPLETE_FAIL("truncate nonexisting file %s failed in %s\n"
                           "Errno %d: %s\n",
                           g_new_filepath, __func__,
                           old_errno, strerror(old_errno));
    }

    if (errno != ENOENT) {
        old_errno = errno;
        TEST_FAIL();
        TEST_COMPLETE_FAIL("truncate nonexisting file %s failed in %s\n"
                           "Errno %d: %s\n",
                           g_new_filepath, __func__,
                           old_errno, strerror(old_errno));
    }

    TEST_OK();

    unlink(g_new_filepath);

    TEST_COMPLETE_OK();
}

int connected(void)
{
    char *test_str = "1";
    char buf[2] = " \0";
    int size = 0;

    size = getxattr(".", "tsumufs.connected", buf, strlen(buf));

    if (size == -1) {
        perror("Unable to getxattr tsumufs.connected from current directory");
        exit(1);
    }

    if (strcmp(buf, test_str) == 0) {
        return 1;
    }

    return 0;
}

int main(void)
{
    int result = 0;
    char *userdir = NULL;

    if ((userdir = getenv("USR_DIR")) == NULL) {
        userdir = ".";
    }

    snprintf(g_existing_filepath, MAXLEN, g_existing_filename, userdir);
    snprintf(g_new_filepath, MAXLEN, g_new_filename, userdir);
    printf("Using existing_filepath: %s, new_filepath: %s\n", 
           g_existing_filepath, 
           g_new_filepath);

    while (!connected()) {
        printf("Waiting for tsumufs to mount.\n");
        sleep(1);
    }
    printf("Mounted.\n");
    sleep(1);

    result = setxattr(".", "tsumufs.pause-sync", "1", strlen("1"), XATTR_REPLACE);
    if (result < 0) {
        perror("Unable to set pause-sync.");
        exit(1);
    }
    result = 0;

    if (!test_ftruncate_existing()) result = 1;
    if (!test_truncate_existing()) result = 1;
    if (!test_ftruncate_new_file()) result = 1;
    if (!test_truncate_new_file()) result = 1;

    return result;
}
