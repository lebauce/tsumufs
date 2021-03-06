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


const char *g_testfilename = "%s/this.file.shouldnt.exist";

char g_testfilepath[MAXLEN];


int test_single_write(void)
{
    const char *output = "Zorba!\n";
    int fd = open(g_testfilepath, O_CREAT|O_RDWR, 0644);
    int total = 0;
    int result = 0;
    int old_errno = errno;

    TEST_START();

    if (fd < 0) {
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to open %s in %s\n"
                           "Errno %d: %s\n",
                           g_testfilepath, __func__,
                           old_errno, strerror(old_errno));
    }
    TEST_OK();

    while (total < strlen(output)) {
        result = write(fd, output + total, strlen(output));

        if (result < 0) {
            old_errno = errno;
            TEST_FAIL();
            TEST_COMPLETE_FAIL("Unable to write to %s in %s\n"
                               "Errno %d: %s\n",
                               g_testfilepath, __func__,
                               old_errno, strerror(old_errno));

            // Don't care about this output -- we're going to die soon, anyway.
            close(fd);
        }

        total += result;
    }
    TEST_OK();

    if (close(fd) < 0) {
        old_errno = errno;

        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to close %s in %s\n"
                           "Errno %d: %s\n",
                           g_testfilepath, __func__,
                           old_errno, strerror(old_errno));
    }
    TEST_OK();

    TEST_COMPLETE_OK();
}

int test_multiple_writes(void)
{
    const char *output = "Zorba!\n";
    int maxcount = 5;
    int fd = open(g_testfilepath, O_CREAT|O_RDWR, 0644);
    int i = 0;
    int total = 0;
    int result = 0;
    int old_errno = errno;

    TEST_START();

    if (fd < 0) {
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to create file %s\n"
                           "Errno %d: %s\n",
                           g_testfilepath, old_errno, strerror(old_errno));
    }
    TEST_OK();

    for (i=0; i<maxcount; i++) {
        total = 0;
        result = 0;

        while (total < strlen(output)) {
            result = write(fd, output + total, strlen(output));
            old_errno = errno;

            if (result < 0) {
                close(fd);

                TEST_FAIL();
                TEST_COMPLETE_FAIL("Unable to write to file %s\n"
                                   "Errno %d: %s\n",
                                   g_testfilepath, old_errno,
                                   strerror(old_errno));
            }

            total += result;
        }
    }
    TEST_OK();

    if (close(fd) < 0) {
        TEST_FAIL();
        TEST_COMPLETE_FAIL("Unable to close %s\nErrno %d: %s\n",
                           g_testfilepath, errno, strerror(errno));
    }
    TEST_OK();

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
    char *userdir;

    if ((userdir = getenv("USR_DIR")) == NULL) {
        userdir = ".";
    }

    snprintf(g_testfilepath, MAXLEN, g_testfilename, userdir);
    printf("Using %s as test file path.\n", g_testfilepath);

    while (!connected()) {
        printf("Waiting for tsumufs to mount.\n");
        sleep(1);
    }
    printf("Mounted.\n");
    sleep(1);

    if (!test_single_write()) result = 1;
    if (!test_multiple_writes()) result = 1;

    return result;
}
